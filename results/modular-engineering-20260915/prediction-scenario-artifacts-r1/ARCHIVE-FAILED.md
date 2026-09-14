# Incomplete archive attempt retained

The first archive helper stopped during independent-input readback. In frozen
source 05f32b4d, the Q5.4 test helper wrote the successful TRAIN call's external
input file and later overwrote that file for its deliberate rejected validation
call. The original TRAIN runtime was unchanged; verification against the later
validation input correctly refused it. This is a test evidence binding defect,
not an accepted artifact or a completed archive.

Files already copied here remain original bytes. There is no success manifest.
The helper, source archives, 66-test result and prior 62-test result are retained.
The fixture helper is repaired by exclusive input creation and separate invalid
calls, then checked under a new frozen source/run and new archive destination.
No original test output was edited and no validation task was executed.
