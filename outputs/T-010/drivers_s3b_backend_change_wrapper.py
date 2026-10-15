"""T-010 S3b driver (prescribed-wrapper E2E): run the UNMODIFIED
run_openfoam_case.py under a simulated backend-identity change.

mesh_cache.detect_backend_identity() (the seam run_openfoam_case.py calls at
:481) is monkey-patched IN MEMORY to return a doctored identity -- one hex
nibble of installation_sha256 flipped, exactly what an OpenFOAM
upgrade/patch would produce (the real function hashes
/usr/share/openfoam/etc/bashrc, a system file we must not touch).

Then run_openfoam_case.main(argv) runs the real prescribed wrapper. argv is
passed through, e.g.:
  --case /home/lenovo2/t010_meshcache/cases/case_h0p4_r0 \
  --steps blockMesh,snappyHexMesh,checkMesh --skip-mesh-if-cached

No code under test is modified on disk; no system file is touched.
"""
import sys

sys.path.insert(0, "/home/lenovo2/t010_meshcache/work/07_cfd_pipeline/solver")
sys.path.insert(0, "/home/lenovo2/t010_meshcache/work/07_cfd_pipeline/solver_reference")
sys.path.insert(0, "/home/lenovo2/t010_meshcache/work/lib")

import mesh_cache
import run_openfoam_case

_real = mesh_cache.detect_backend_identity()
_first = "f" if _real["installation_sha256"][0] != "f" else "0"
_doctored = dict(_real)
_doctored["installation_sha256"] = _first + _real["installation_sha256"][1:]


def _patched_identity():
    return dict(_doctored)


mesh_cache.detect_backend_identity = _patched_identity

print("S3b wrapper: patched detect_backend_identity")
print("  real installation_sha256   :", _real["installation_sha256"])
print("  doctored installation_sha256:", _doctored["installation_sha256"])
raise SystemExit(run_openfoam_case.main(sys.argv[1:]))
