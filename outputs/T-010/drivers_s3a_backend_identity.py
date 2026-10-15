"""T-010 S3a driver (API level): backend identity change must alter the signature.

Imports the UNMODIFIED mesh_cache.py copied byte-identically from the repo and:
  1. computes the signature with the real detect_backend_identity();
  2. computes the signature with a doctored identity (one hex nibble of
     installation_sha256 flipped -- exactly what a backend upgrade/patch would
     do to detect_backend_identity(), which hashes /usr/share/openfoam/etc/bashrc);
  3. runs inspect_reuse() against the live case with both signatures.

No code under test is modified; no system file is touched.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/home/lenovo2/t010_meshcache/work/07_cfd_pipeline/solver")
import mesh_cache

CASE = Path("/home/lenovo2/t010_meshcache/cases/case_h0p4_r0")

real = mesh_cache.detect_backend_identity()
doctored = dict(real)
first = "f" if real["installation_sha256"][0] != "f" else "0"
doctored["installation_sha256"] = first + real["installation_sha256"][1:]

print("real installation_sha256   :", real["installation_sha256"])
print("doctored installation_sha256:", doctored["installation_sha256"])

sig_real = mesh_cache.mesh_inputs_signature(CASE, real)
sig_doc = mesh_cache.mesh_inputs_signature(CASE, doctored)
print("signature(real)   :", sig_real.get("signature"), "valid:", sig_real.get("valid"))
print("signature(doctored):", sig_doc.get("signature"), "valid:", sig_doc.get("valid"))
print("signatures differ :", sig_real.get("signature") != sig_doc.get("signature"))

reuse_real = mesh_cache.inspect_reuse(CASE, sig_real)
reuse_doc = mesh_cache.inspect_reuse(CASE, sig_doc)
print("inspect_reuse(real)   : reusable =", reuse_real.get("reusable"), "|", reuse_real.get("reason"))
print("inspect_reuse(doctored): reusable =", reuse_doc.get("reusable"), "|", reuse_doc.get("reason"))
