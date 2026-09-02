--------------------------------- MODULE HoldSpec ---------------------------------
(***************************************************************************)
(* HoldSpec: an abstract state machine for the payment authorization hold   *)
(* lifecycle exposed by card payment service providers (PSPs).              *)
(*                                                                          *)
(* The machine covers one authorization and the operations a merchant may   *)
(* perform on it: capture (partial, multiple, final), void, expiry,         *)
(* incremental authorization, and the release of the funds a PSP holds on   *)
(* the cardholder's account.                                                *)
(*                                                                          *)
(* The spec is parameterized by a PROVIDER PROFILE: the capability vector   *)
(* that a concrete PSP exposes (whether more than one capture is allowed,   *)
(* how much may be captured above the authorized amount, whether a void is  *)
(* accepted once a capture has happened, how long an authorization stays    *)
(* valid, and how promptly held funds must be released).  Profiles are      *)
(* supplied as TLC constants; see spec/profiles/.                           *)
(*                                                                          *)
(* Money is in integer minor units.  Time is in abstract ticks; a tick maps *)
(* to whatever granularity a profile's Validity is expressed in.            *)
(***************************************************************************)
EXTENDS Integers, TLC

CONSTANTS
    AuthAmount,            \* amount authorized by the Authorize action
    MaxAuthAmount,         \* ceiling on the authorized amount after increments
    OverCaptureAllowance,  \* units capturable ABOVE the authorized amount (0 = forbidden)
    MaxNonFinalCaptures,   \* non-final captures the profile permits (0 = single capture)
    SupportsIncrementalAuth,  \* BOOLEAN: profile permits raising the authorized amount
    SupportsFinalCapture,  \* BOOLEAN: the API can say "this capture is the last one"
    VoidAfterPartial,      \* BOOLEAN: profile accepts a void once a capture has happened
    Validity,              \* ticks after Authorize at which the hold expires
    MaxReleaseDelay,       \* ticks within which held funds must be released after close
    Horizon                \* bound on the clock

VARIABLES
    state,           \* "NONE" | "HELD" | "CLOSED"
    closedBy,        \* "-" | "CAPTURE" | "VOID" | "EXPIRY"
    authAmt,         \* currently authorized amount
    capturedTotal,   \* sum of all captures so far
    capturedAtClose, \* capturedTotal recorded at the moment the hold closed
    captureCount,    \* number of capture calls accepted
    lastCaptureAt,   \* clock value of the most recent non-zero capture
    released,        \* number of hold-release events observed
    expiresAt,       \* clock value at which the authorization expires
    releaseDue,      \* clock value by which held funds must have been released
    clock

vars == << state, closedBy, authAmt, capturedTotal, capturedAtClose,
           captureCount, lastCaptureAt, released, expiresAt, releaseDue, clock >>

NoTime == Horizon + 1

\* The most a merchant may ever have captured, given the profile's over-capture rule.
CaptureLimit == authAmt + OverCaptureAllowance

\* Funds the PSP is still holding on the cardholder's account.
Shortfall(x) == IF x >= authAmt THEN 0 ELSE authAmt - x

HeldAmount ==
    IF state = "HELD" THEN Shortfall(capturedTotal)
    ELSE IF released = 0 THEN Shortfall(capturedAtClose)
    ELSE 0

-----------------------------------------------------------------------------
(* Actions *)

\* The clock is relative to the authorization, so the hold is created at t = 0.
Authorize ==
    /\ state = "NONE"
    /\ state' = "HELD"
    /\ authAmt' = AuthAmount
    /\ expiresAt' = clock + Validity
    /\ UNCHANGED << closedBy, capturedTotal, capturedAtClose, captureCount,
                    lastCaptureAt, released, releaseDue, clock >>

\* A capture that deliberately leaves the remaining authorized amount in place.
\* Only profiles with MaxNonFinalCaptures > 0 (Stripe multicapture, Adyen with
\* multiple partial captures enabled) offer this.
\* Where there is no final-capture flag, a capture that takes the whole
\* authorized amount necessarily ends the hold -- nothing is left to hold -- so
\* it is a closing capture, not a non-final one.  Where the flag exists, the
\* merchant may capture everything and still keep the authorization open.
CaptureNonFinal(c) ==
    /\ state = "HELD"
    /\ clock < expiresAt
    /\ captureCount < MaxNonFinalCaptures
    /\ c > 0
    /\ (SupportsFinalCapture \/ capturedTotal + c < authAmt)
    /\ capturedTotal + c =< CaptureLimit
    /\ capturedTotal' = capturedTotal + c
    /\ captureCount'  = captureCount + 1
    /\ lastCaptureAt' = clock
    /\ UNCHANGED << state, closedBy, authAmt, capturedAtClose, released,
                    expiresAt, releaseDue, clock >>

\* A capture that closes the hold and releases whatever is left.  c = 0 is the
\* documented way to release a remainder after non-final captures, so it is
\* allowed only when a capture has already happened.
\*
\* Not every API can say "this is the last capture".  Stripe has final_capture;
\* Adyen, once multiple partial captures are enabled, has no such flag, and a
\* merchant closes the hold either by capturing the whole authorized amount --
\* leaving nothing to hold -- or by cancelling what is left.  SupportsFinalCapture
\* carries that difference.
CaptureFinal(c) ==
    /\ state = "HELD"
    /\ clock < expiresAt
    /\ c >= 0
    /\ (c = 0 => captureCount > 0)
    /\ (SupportsFinalCapture \/ capturedTotal + c = authAmt)
    /\ capturedTotal + c =< CaptureLimit
    /\ state'           = "CLOSED"
    /\ closedBy'        = "CAPTURE"
    /\ capturedTotal'   = capturedTotal + c
    /\ capturedAtClose' = capturedTotal + c
    /\ captureCount'    = captureCount + 1
    /\ lastCaptureAt'   = IF c > 0 THEN clock ELSE lastCaptureAt
    /\ releaseDue'      = clock + MaxReleaseDelay
    /\ UNCHANGED << authAmt, released, expiresAt, clock >>

Void ==
    /\ state = "HELD"
    /\ clock < expiresAt
    /\ (capturedTotal = 0 \/ VoidAfterPartial)
    /\ state'           = "CLOSED"
    /\ closedBy'        = "VOID"
    /\ capturedAtClose' = capturedTotal
    /\ releaseDue'      = clock + MaxReleaseDelay
    /\ UNCHANGED << authAmt, capturedTotal, captureCount, lastCaptureAt,
                    released, expiresAt, clock >>

Expire ==
    /\ state = "HELD"
    /\ clock >= expiresAt
    /\ state'           = "CLOSED"
    /\ closedBy'        = "EXPIRY"
    /\ capturedAtClose' = capturedTotal
    /\ releaseDue'      = clock + MaxReleaseDelay
    /\ UNCHANGED << authAmt, capturedTotal, captureCount, lastCaptureAt,
                    released, expiresAt, clock >>

\* Releasing the hold is a separate observable event from closing it.  Keeping
\* the two apart is what makes "released exactly once" and "released promptly"
\* properties worth checking rather than true by construction.
\* releaseDue is left in place rather than cleared.  Keeping the deadline after
\* the fact is what lets an observer say a release was late: clear it and a
\* provider that released too slowly becomes indistinguishable from one that
\* released on time.
ReleaseHold ==
    /\ state = "CLOSED"
    /\ released = 0
    /\ released' = 1
    /\ UNCHANGED << state, closedBy, authAmt, capturedTotal, capturedAtClose,
                    captureCount, lastCaptureAt, expiresAt, releaseDue, clock >>

IncreaseAuth(d) ==
    /\ SupportsIncrementalAuth
    /\ state = "HELD"
    /\ clock < expiresAt
    /\ d > 0
    /\ authAmt + d =< MaxAuthAmount
    /\ authAmt' = authAmt + d
    /\ UNCHANGED << state, closedBy, capturedTotal, capturedAtClose, captureCount,
                    lastCaptureAt, released, expiresAt, releaseDue, clock >>

\* Time may not run past a release that is already due.  This is the standard
\* upper-bound-timer idiom for real time in TLA+ (Abadi and Lamport): an action
\* with a deadline blocks the clock rather than being silently missed, so a
\* missed deadline shows up as a timelock (deadlock) rather than as an
\* unnoticed violation.
ReleasePending == state = "CLOSED" /\ released = 0

\* The authorization expires at its deadline: once the clock reaches expiresAt
\* the hold must close before time moves on.  Releasing the funds the hold was
\* reserving is allowed to lag, but only by MaxReleaseDelay ticks.
ExpiryPending == state = "HELD" /\ clock >= expiresAt

Tick ==
    /\ state /= "NONE"
    /\ clock < Horizon
    /\ ~ExpiryPending
    /\ (ReleasePending => clock + 1 =< releaseDue)
    /\ clock' = clock + 1
    /\ UNCHANGED << state, closedBy, authAmt, capturedTotal, capturedAtClose,
                    captureCount, lastCaptureAt, released, expiresAt, releaseDue >>

\* Terminal stutter, so that a finished behavior at the horizon is not a deadlock.
Done ==
    /\ clock = Horizon
    /\ (state = "CLOSED" => released = 1)
    /\ state /= "NONE"
    /\ UNCHANGED vars

CaptureAmounts    == 1..(MaxAuthAmount + OverCaptureAllowance)
FinalAmounts      == 0..(MaxAuthAmount + OverCaptureAllowance)
IncrementAmounts  == 1..MaxAuthAmount

Next ==
    \/ Authorize
    \/ \E c \in CaptureAmounts   : CaptureNonFinal(c)
    \/ \E c \in FinalAmounts     : CaptureFinal(c)
    \/ \E d \in IncrementAmounts : IncreaseAuth(d)
    \/ Void
    \/ Expire
    \/ ReleaseHold
    \/ Tick
    \/ Done

Fairness ==
    /\ WF_vars(Authorize)
    /\ WF_vars(Tick)
    /\ WF_vars(Expire)
    /\ WF_vars(ReleaseHold)

Init ==
    /\ state           = "NONE"
    /\ closedBy        = "-"
    /\ authAmt         = 0
    /\ capturedTotal   = 0
    /\ capturedAtClose = 0
    /\ captureCount    = 0
    /\ lastCaptureAt   = NoTime
    /\ released        = 0
    /\ expiresAt       = NoTime
    /\ releaseDue      = NoTime
    /\ clock           = 0

Spec == Init /\ [][Next]_vars /\ Fairness

-----------------------------------------------------------------------------
(* Safety properties *)

\* released is typed 0..2 on purpose: a double release must be caught by
\* INV_ReleaseAtMostOnce, not silently by the type invariant.
TypeOK ==
    /\ state           \in {"NONE", "HELD", "CLOSED"}
    /\ closedBy        \in {"-", "CAPTURE", "VOID", "EXPIRY"}
    /\ authAmt         \in 0..MaxAuthAmount
    /\ capturedTotal   \in 0..(MaxAuthAmount + OverCaptureAllowance)
    /\ capturedAtClose \in 0..(MaxAuthAmount + OverCaptureAllowance)
    /\ captureCount    \in 0..(MaxNonFinalCaptures + 1)
    /\ lastCaptureAt   \in 0..NoTime
    /\ released        \in 0..2
    /\ expiresAt       \in 0..NoTime
    /\ releaseDue      \in 0..NoTime
    /\ clock           \in 0..Horizon

\* H1  Captures never exceed what the profile authorizes.
INV_CaptureWithinLimit == capturedTotal =< authAmt + OverCaptureAllowance

\* H2  Nothing is captured after the hold has closed (void, expiry, or final capture).
INV_NoCaptureAfterClose == (state = "CLOSED") => (capturedTotal = capturedAtClose)

\* H3  Held funds are released at most once.
INV_ReleaseAtMostOnce == released =< 1

\* H4  Held funds are not released while the hold is still open.
INV_NoReleaseBeforeClose == (state /= "CLOSED") => (released = 0)

\* H5  Once closed, the release happens within the profile's release deadline.
INV_BoundedRelease == (state = "CLOSED" /\ released = 0) => (clock =< releaseDue)

\* H6  No capture is accepted at or after the expiry instant.
INV_NoCaptureAfterExpiry == (capturedTotal > 0) => (lastCaptureAt < expiresAt)

\* H7  A profile's capture-count budget is respected.
INV_CaptureCountWithinProfile == captureCount =< MaxNonFinalCaptures + 1

\* H8  A released hold leaves nothing held.
INV_HoldFullyReleased == (state = "CLOSED" /\ released = 1) => (HeldAmount = 0)

Safety ==
    /\ TypeOK
    /\ INV_CaptureWithinLimit
    /\ INV_NoCaptureAfterClose
    /\ INV_ReleaseAtMostOnce
    /\ INV_NoReleaseBeforeClose
    /\ INV_BoundedRelease
    /\ INV_NoCaptureAfterExpiry
    /\ INV_CaptureCountWithinProfile
    /\ INV_HoldFullyReleased

-----------------------------------------------------------------------------
(* Liveness properties *)

\* L1  A closed hold eventually releases the funds it was holding.
LIVE_EventualRelease == [](state = "CLOSED" => <>(released = 1))

\* L2  An open hold does not stay open forever: expiry closes it if nothing else does.
LIVE_EventualClose == [](state = "HELD" => <>(state = "CLOSED"))

\* L3  Every behavior reaches a settled end state.
LIVE_Termination == <>(state = "CLOSED" /\ released = 1)

=============================================================================
