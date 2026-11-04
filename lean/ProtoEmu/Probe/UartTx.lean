/-!
# Probe A: a protocol-level proof for a UART TX firmware

A minimal timeline ISA (a subset of the ISA v0 draft), a UART 8N1 frame spec
written from the standard, and a proof that one firmware emits a valid frame
for every byte and every bit period `p ≥ 4`, with no late timed action.

The model counts cycles with unbounded `Nat`. The 16-bit wrap of the RTL timer
is out of scope here.
-/

namespace ProtoEmu.Probe

/-! ## Pin traces and the UART spec -/

/-- A pin event: from cycle `e.1` on, the pin has level `e.2`. -/
abbrev Event := Nat × Bool

/-- The pin level at cycle `t`: the value of the last event at or before `t`,
or `idle` if there is none. -/
def level (idle : Bool) (evs : List Event) (t : Nat) : Bool :=
  evs.foldl (fun acc e => if e.1 ≤ t then e.2 else acc) idle

/-- Bit `k` of `b`, LSB first. -/
def bit (b k : Nat) : Bool := b / 2 ^ k % 2 == 1

/-- A UART 8N1 frame of byte `b` with bit period `p` that starts at cycle `t0`,
on the line `w` (level per cycle). Start bit low, eight data bits LSB first,
stop bit high, each one bit period long. -/
def UartFrame (w : Nat → Bool) (t0 p b : Nat) : Prop :=
  (∀ t, t0 ≤ t → t < t0 + p → w t = false) ∧
  (∀ k, k < 8 → ∀ t, t0 + (k + 1) * p ≤ t → t < t0 + (k + 2) * p → w t = bit b k) ∧
  (∀ t, t0 + 9 * p ≤ t → t < t0 + 10 * p → w t = true)

/-! ## The machine -/

inductive Instr where
  /-- `r1 ← v` -/
  | ldi1 (v : Nat)
  /-- timed: drive the pin low at `T` -/
  | pinLow
  /-- timed: drive the pin high at `T` -/
  | pinHigh
  /-- timed: drive the pin to bit 0 of `r0` at `T`, then `r0 ← r0 / 2` -/
  | put
  /-- `T ← T + d` -/
  | dly (d : Nat)
  /-- `r1 ← r1 - 1`, jump to `tgt` if the result is not 0 (2 cycles if taken) -/
  | djnz (tgt : Nat)
  /-- stall until `T` -/
  | waitT
  | halt

structure St where
  pc : Nat
  now : Nat
  T : Nat
  r0 : Nat
  r1 : Nat
  late : Bool
  halted : Bool
  evs : List Event

/-- A timed pin action. It acts at cycle `max now T`. If the core arrives after
`T`, it still acts and sets `late`. -/
def pinAct (s : St) (v : Bool) : St :=
  { s with now := max s.now s.T + 1, pc := s.pc + 1,
           late := s.late || decide (s.T < s.now),
           evs := s.evs ++ [(max s.now s.T, v)] }

def exec (i : Instr) (s : St) : St :=
  match i with
  | .ldi1 v => { s with r1 := v, now := s.now + 1, pc := s.pc + 1 }
  | .pinLow => pinAct s false
  | .pinHigh => pinAct s true
  | .put => { pinAct s (bit s.r0 0) with r0 := s.r0 / 2 }
  | .dly d => { s with T := s.T + d, now := s.now + 1, pc := s.pc + 1 }
  | .djnz tgt =>
    if s.r1 - 1 = 0 then { s with r1 := 0, now := s.now + 1, pc := s.pc + 1 }
    else { s with r1 := s.r1 - 1, now := s.now + 2, pc := tgt }
  | .waitT => { s with now := max s.now s.T + 1, pc := s.pc + 1 }
  | .halt => { s with halted := true }

def step (prog : List Instr) (s : St) : St :=
  if s.halted then s else
  match prog[s.pc]? with
  | some i => exec i s
  | none => { s with halted := true }

def run (prog : List Instr) : Nat → St → St
  | 0, s => s
  | n + 1, s => run prog n (step prog s)

/-! ## The firmware -/

/-- UART TX of the byte in `r0`, bit period `p`, frame start at `T`. -/
def uartTx (p : Nat) : List Instr :=
  [.ldi1 8, .pinLow, .dly p, .put, .dly p, .djnz 3, .pinHigh, .dly p, .waitT, .halt]

/-- Start state: byte `b` in `r0`, timeline cursor at the frame start `t0`,
core at cycle `n`. -/
def init (b t0 n : Nat) : St :=
  { pc := 0, now := n, T := t0, r0 := b, r1 := 0, late := false, halted := false, evs := [] }


/-! ## Proofs -/

theorem run_add (prog : List Instr) (a b : Nat) (s : St) :
    run prog (a + b) s = run prog b (run prog a s) := by
  induction a generalizing s with
  | zero => simp [run]
  | succ a ih =>
    rw [Nat.add_right_comm, run, ih, run]

theorem bit_half (r j : Nat) : bit (r / 2) j = bit r (j + 1) := by
  simp only [bit, Nat.div_div_eq_div_mul, Nat.pow_succ, Nat.mul_comm]

/-- `m + 1` passes of the bit loop (`put`, `dly p`, `djnz 3`) from a state at
`pc = 3` that is on time. -/
theorem loop (p : Nat) (hp : 4 ≤ p) :
    ∀ m, ∀ s : St, s.pc = 3 → s.r1 = m + 1 → s.halted = false → s.now ≤ s.T →
      run (uartTx p) (3 * (m + 1)) s =
        { s with pc := 6, r1 := 0, r0 := s.r0 / 2 ^ (m + 1), T := s.T + (m + 1) * p,
                 now := s.T + m * p + 3,
                 evs := s.evs ++ (List.range (m + 1)).map (fun j => (s.T + j * p, bit s.r0 j)) } := by
  intro m
  induction m with
  | zero =>
    intro s hpc hr1 hh hle
    obtain ⟨pc, now, T, r0, r1, late, halted, evs⟩ := s
    simp only at hpc hr1 hh hle
    subst hpc hr1 hh
    have hmax : max now T = T := Nat.max_eq_right hle
    have hlt : decide (T < now) = false := by simp; omega
    simp [run, step, exec, pinAct, uartTx, hmax, hlt]
  | succ m ih =>
    intro s hpc hr1 hh hle
    obtain ⟨pc, now, T, r0, r1, late, halted, evs⟩ := s
    simp only at hpc hr1 hh hle
    subst hpc hr1 hh
    have hmax : max now T = T := Nat.max_eq_right hle
    have hlt : decide (T < now) = false := by simp; omega
    have hne : m + 1 + 1 - 1 ≠ 0 := by omega
    rw [show 3 * (m + 1 + 1) = 3 + 3 * (m + 1) by omega, run_add]
    have h3 : run (uartTx p) 3 ⟨3, now, T, r0, m + 1 + 1, late, false, evs⟩ =
        ⟨3, T + 4, T + p, r0 / 2, m + 1, late, false, evs ++ [(T, bit r0 0)]⟩ := by
      simp [run, step, exec, pinAct, uartTx, hmax, hlt, hne]
    rw [h3, ih ⟨3, T + 4, T + p, r0 / 2, m + 1, late, false, evs ++ [(T, bit r0 0)]⟩
      rfl rfl rfl (by simp; omega)]
    simp only [St.mk.injEq, true_and, Nat.div_div_eq_div_mul, List.append_assoc]
    refine ⟨?_, ?_, ?_, ?_⟩
    · simp only [Nat.add_mul, Nat.one_mul]; omega
    · simp only [Nat.add_mul, Nat.one_mul]; omega
    · rw [show 2 ^ (m + 1 + 1) = 2 * 2 ^ (m + 1) by rw [Nat.pow_succ, Nat.mul_comm]]
    · rw [List.range_succ_eq_map (n := m + 1), List.map_cons, List.map_map]
      simp only [Nat.zero_mul, Nat.add_zero, List.singleton_append, List.append_cancel_left_eq,
        List.cons.injEq, true_and]
      apply List.map_congr_left
      intro j _
      simp only [Function.comp, Nat.succ_eq_add_one, bit_half, Prod.mk.injEq, and_true]
      simp only [Nat.add_mul, Nat.one_mul]; omega

/-- The whole run: 31 steps from the start state. -/
theorem final_state (b p t0 n : Nat) (hp : 4 ≤ p) (hn : n < t0) :
    run (uartTx p) 31 (init b t0 n) =
      { pc := 9, now := t0 + 10 * p + 1, T := t0 + 10 * p, r0 := b / 2 ^ 8, r1 := 0,
        late := false, halted := true,
        evs := [(t0, false)] ++ (List.range 8).map (fun j => (t0 + p + j * p, bit b j)) ++
               [(t0 + 9 * p, true)] } := by
  rw [show (31 : Nat) = 3 + (3 * 8 + 4) by rfl, run_add, run_add]
  have hmax : max (n + 1) t0 = t0 := Nat.max_eq_right hn
  have hlt : decide (t0 < n + 1) = false := by simp; omega
  have h3 : run (uartTx p) 3 (init b t0 n) =
      ⟨3, t0 + 2, t0 + p, b, 8, false, false, [(t0, false)]⟩ := by
    simp [run, step, exec, pinAct, uartTx, init, hmax, hlt]
  rw [h3, loop p hp 7 _ rfl rfl rfl (by simp; omega)]
  simp only
  have hmax2 : max (t0 + p + 7 * p + 3) (t0 + p + (7 + 1) * p) = t0 + p + (7 + 1) * p := by
    apply Nat.max_eq_right; omega
  have hlt2 : decide (t0 + p + (7 + 1) * p < t0 + p + 7 * p + 3) = false := by simp; omega
  simp [run, step, exec, pinAct, uartTx, hmax2, hlt2]
  exact ⟨by omega, by omega, by omega⟩


/-! ## From the event list to the UART spec -/

theorem foldl_skip (t : Nat) (l : List Event) (acc : Bool) (h : ∀ e ∈ l, t < e.1) :
    l.foldl (fun acc e => if e.1 ≤ t then e.2 else acc) acc = acc := by
  induction l generalizing acc with
  | nil => rfl
  | cons e l ih =>
    have he : ¬ e.1 ≤ t := by have := h e (List.mem_cons_self ..); omega
    rw [List.foldl_cons, if_neg he]
    exact ih acc (fun x hx => h x (List.mem_cons_of_mem _ hx))

/-- The level at `t` is the value of an event at or before `t` when every later
event in the list comes after `t`. -/
theorem level_at (idle : Bool) (pre post : List Event) (ti : Nat) (v : Bool) (t : Nat)
    (h1 : ti ≤ t) (h2 : ∀ e ∈ post, t < e.1) :
    level idle (pre ++ (ti, v) :: post) t = v := by
  unfold level
  rw [List.foldl_append, List.foldl_cons, if_pos h1, foldl_skip t post v h2]

theorem level_none (idle : Bool) (evs : List Event) (t : Nat) (h : ∀ e ∈ evs, t < e.1) :
    level idle evs t = idle :=
  foldl_skip t evs idle h

theorem range8_split (k : Nat) (hk : k < 8) :
    List.range 8 = List.range k ++ k :: List.range' (k + 1) (7 - k) := by
  have h := @List.range'_append 0 k (7 - k + 1) 1
  rw [List.range'_succ] at h
  simp only [Nat.zero_add, Nat.one_mul] at h
  rw [List.range_eq_range', List.range_eq_range', h]
  congr 1
  omega

/-- **Probe A result.** For every byte `b`, every bit period `p ≥ 4`, and every
frame start `t0` after the core starts: the firmware halts, no timed action is
late, the line is idle high before `t0`, the pin trace is a UART 8N1 frame of
`b`, and the program ends after the stop bit. -/
theorem uartTx_correct (b p t0 n : Nat) (hp : 4 ≤ p) (hn : n < t0) :
    let s := run (uartTx p) 31 (init b t0 n)
    s.halted = true ∧ s.late = false ∧ t0 + 10 * p ≤ s.now ∧
    (∀ t, t < t0 → level true s.evs t = true) ∧
    UartFrame (level true s.evs) t0 p b := by
  rw [final_state b p t0 n hp hn]
  refine ⟨rfl, rfl, by simp only; omega, ?_, ?_, ?_, ?_⟩
  · -- idle before the frame
    intro t ht
    apply level_none
    intro e he
    simp only [List.mem_append, List.mem_cons, List.mem_map, List.mem_range,
      List.not_mem_nil, or_false] at he
    rcases he with (he | ⟨j, _, rfl⟩) | he <;> (try subst he) <;> simp only <;> omega
  · -- start bit
    intro t h1 h2
    show level true ([] ++ (t0, false) ::
      ((List.range 8).map (fun j => (t0 + p + j * p, bit b j)) ++ [(t0 + 9 * p, true)])) t = false
    apply level_at _ _ _ _ _ _ h1
    intro e he
    simp only [List.mem_append, List.mem_cons, List.mem_map, List.mem_range,
      List.not_mem_nil, or_false] at he
    rcases he with ⟨j, _, rfl⟩ | rfl <;> simp only <;> omega
  · -- data bits
    intro k hk t h1 h2
    rw [range8_split k hk, List.map_append, List.map_cons]
    simp only [List.append_assoc, List.cons_append, List.singleton_append]
    rw [← List.cons_append]
    apply level_at
    · simp only [Nat.add_mul, Nat.one_mul] at h1; omega
    · intro e he
      simp only [List.mem_append, List.mem_cons, List.mem_map, List.mem_range'_1,
        List.not_mem_nil, or_false] at he
      rcases he with ⟨j, ⟨hj, _⟩, rfl⟩ | rfl
      · have := Nat.mul_le_mul_right p hj
        simp only [Nat.add_mul, Nat.one_mul] at this h2 ⊢; omega
      · have := Nat.mul_le_mul_right p (show k + 2 ≤ 9 by omega)
        simp only at this ⊢; omega
  · -- stop bit
    intro t h1 h2
    exact level_at _ _ [] _ _ _ h1 (by simp)

/-- The bound `p ≥ 4` is tight: at `p = 3` the loop arrives one cycle late. -/
example : (run (uartTx 3) 31 (init 0xA5 10 0)).late = true := by decide


/-! ## Teeth: mutant firmwares that the spec catches

Each mutant breaks one clause of `UartFrame` on a concrete frame (`p = 4`, `t0 = 10`).
The spec checks the right things, not only the shape of the trace. -/

/-- Mutant: stop bit driven low. -/
def uartTxBadStop (p : Nat) : List Instr :=
  [.ldi1 8, .pinLow, .dly p, .put, .dly p, .djnz 3, .pinLow, .dly p, .waitT, .halt]

/-- Mutant: only 7 data bits. -/
def uartTxSevenBits (p : Nat) : List Instr :=
  [.ldi1 7, .pinLow, .dly p, .put, .dly p, .djnz 3, .pinHigh, .dly p, .waitT, .halt]

/-- The stop bit cycle `t0 + 9p = 46` reads low, where the spec needs high. -/
example : level true (run (uartTxBadStop 4) 31 (init 0xA5 10 0)).evs 46 = false := by decide

/-- The 7-bit mutant sends its stop bit (high) in bit 7's slot, cycle
`t0 + 8p = 42`. For byte `0x25`, bit 7 is 0, so the spec needs low there. -/
example : bit 0x25 7 = false ∧
    level true (run (uartTxSevenBits 4) 31 (init 0x25 10 0)).evs 42 = true := by decide

end ProtoEmu.Probe
