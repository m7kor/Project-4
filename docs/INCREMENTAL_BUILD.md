# Local declarations for generated game bodies

Adding one discovered RE4 entry changed `ps2_recompiled_functions.h`, invalidating thousands of generated source objects. The measured build after adding `0x1B36F0` executed 8,450 tasks and took 708.8 seconds. Unchanged source files were already preserved by the generator; the dependency on the shared function-map header caused the rebuild.

Individual generated bodies now omit the shared function-map header. Direct function jumps and known jump-table calls emit an explicit declaration of the target they use. Registration and the runner still include the complete function header. Runtime and stub headers remain available. This changes compile dependencies, not guest instruction execution or assets.

`python -m ps2l canary --tailcall` creates two separately mapped synthetic EE functions. The first directly jumps into the second; the native result must be `v0=17`, zero probe slots, and return PC `0x123456`. It then adds an unrelated function declaration to the map header and checks that both generated object modification times remain unchanged. The harness still rebuilds as appropriate for its header dependency.

The pre-change executable-build probe failed the dependency check (`artifacts/canary-tailcall-before/report.json`). The new generator passes both the dependency check and native execution (`artifacts/canary-tailcall/report.json`). Combined verification also passed all 457 C++ tests, Python regressions, map/profile checks and four native canaries in `artifacts/tool-audit/20261006/verify-local-declarations.json`.

The first full RE4 runner build with this change passed in 568.8 seconds. The actual dependency record for a generated RE4 object no longer contains the global function-map header (`artifacts/tool-audit/20261006/actual-function-dependencies.log`). The native run also passed the previously missing entries and continued, but its frames remained black. Changing every source's includes required this broad rebuild; a future real-game map addition and measured build are still needed before claiming a measured incremental RE4 speedup. Full gameplay compatibility remains unverified.
