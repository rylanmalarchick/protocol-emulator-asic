import ProtoEmu.Net.UartTx

/-!
# Properties of the generated `uart_tx` netlist model

`ProtoEmu.Net.UartTx` is generated from the yosys gate netlist of `uart_tx.v`
(16 clocks per bit). These are hand-written proofs about that model.
-/

namespace ProtoEmu.Net.UartTx

/-- `n` clock edges with input `inp t` at cycle `t`. -/
def runN (inp : Nat → In) : Nat → St
  | 0 => init
  | n + 1 => step (runN inp n) (inp n)

/-- In the idle state with `start` low, one clock edge keeps the idle state and
keeps `tx` high, whatever the other registers and `data_in` hold. -/
theorem step_idle (s : St) (i : In) (h0 : s.state_0 = false) (h1 : s.state_1 = false)
    (hs : i.start = false) :
    (step s i).state_0 = false ∧ (step s i).state_1 = false ∧ (step s i).tx = true := by
  obtain ⟨_, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _, _⟩ := s
  obtain ⟨_, _, _, _, _, _, _, _, _⟩ := i
  simp only at h0 h1 hs
  subst h0 h1 hs
  simp [step]

/-- Pilot property P1, proved locally on the netlist model: if `start` is low in
every cycle, `tx` is high in every cycle. -/
theorem idle_high (inp : Nat → In) (h : ∀ t, (inp t).start = false) :
    ∀ n, (runN inp n).tx = true := by
  have inv : ∀ n, (runN inp n).state_0 = false ∧ (runN inp n).state_1 = false ∧
      (runN inp n).tx = true := by
    intro n
    induction n with
    | zero => exact ⟨rfl, rfl, rfl⟩
    | succ n ih => exact step_idle _ _ ih.1 ih.2.1 (h n)
  exact fun n => (inv n).2.2


/-- `start` with byte `0xA5` in cycle 0, `start` low afterwards. -/
def inpA5 (t : Nat) : In :=
  { start := t == 0, data_in_0 := true, data_in_1 := false, data_in_2 := true,
    data_in_3 := false, data_in_4 := false, data_in_5 := true, data_in_6 := false,
    data_in_7 := true }

/-- Expected `tx`: idle, start bit in cycles 2..17, data LSB first, stop bit,
16 cycles per bit. -/
def expectedTx (n : Nat) : Bool :=
  if n < 2 then true
  else if n < 18 then false
  else if n < 146 then (0xA5 : Nat).testBit ((n - 18) / 16)
  else true

set_option maxRecDepth 100000 in
/-- One full frame of `0xA5` on the netlist model, checked cycle by cycle by
the kernel. -/
theorem frame_A5 : ∀ n, n < 170 → (runN inpA5 n).tx = expectedTx n := by decide

end ProtoEmu.Net.UartTx
