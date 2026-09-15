# Pure evaluator descriptor and primary controller gate

Frozen source `2113371268b30411712273623371cbcf49e0ccc8` passed 20 checks
in 318.234 seconds. All 775 source/document files were byte-identical before
and after. This gate covers exact descriptor parity without opening a ledger,
strict recovery declarations, the actual eight-cell solver/Docker/private
stdio scorer lifecycle, and ten label-isolation checks.

Model and account responses were synthetic; Docker and scoring subprocesses
were real. The eight-cell positive case recorded 40 synthetic solver calls
and eight synthetic evaluator calls. This is engineering evidence, not an
actual benchmark effect or validation result.

`published-manifest.json` preserves the original staging manifest unchanged.
The private retained archive has 1,819 noncredential files from ten explicit
test roots; 65 authentication/key files were excluded. Original bytes and
mtime were checked by the archival helper. The private manifest preserves
every included descriptor and each exclusion. No pytest current-directory
link was followed. `delivery-manifest.json` covers every published file
other than itself; source bytes and JUnit originals are included here.

The actual TRAIN runtime is frozen separately at this source commit. Later
lineage controller changes do not retroactively change this gate or runtime.
