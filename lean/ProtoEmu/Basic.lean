/-!
# ProtoEmu

ISA model and latency proofs for the protocol emulator (D4, option B).

This file holds only a toolchain check. The ISA model replaces it when
`docs/isa.md` v0 exists.
-/

namespace ProtoEmu

/-- Toolchain check: the build and the axiom audit run. Remove with the first real theorem. -/
theorem toolchain_check : (2 : Nat) + 2 = 4 := rfl

end ProtoEmu
