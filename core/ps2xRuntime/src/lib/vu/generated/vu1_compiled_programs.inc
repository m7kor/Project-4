// Source distribution fallback: no game-derived microprograms are shipped.
// Returning nullptr selects the existing VU1 interpreter. Replace locally with
// ps2x_vu1_codegen output from your own captures to enable compiled programs.
static const VU1Interpreter::CompiledPairFn *vu1FindCompiledProgram(uint64_t)
{
    return nullptr;
}
