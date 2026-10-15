"""T-042: whole-domain momentum closure check on the PATIENT case (b15 maxh1).

Why this exists
---------------
`verify_wss_force_balance.py` validated the WSS *code path* against the analytic
plane-Poiseuille force balance on the reference case. That check cannot run on
the patient geometry (not fully developed). This script closes the loop on the
patient case itself with the global steady momentum balance:

    -F_p + F_w = F_m        (all vectors; outward normals from Newell)

    F_p = sum over ALL patches of  integral  p * n dA        (rho * kinematic p)
    F_m = sum over ALL patches of  integral  rho * U * (U.n) dA
    F_w = integral over wall patch of  tau * dA              (rho * kinematic)

Sign of F_w follows OpenFOAM's wallShearStress convention; both signs are
reported and the one that closes the balance is identified. This is a CLOSURE
(sanity) check, not a pass criterion -- residuals come from discrete
integration, the not-fully-converged field, and pressure/velocity coupling.

Output: outputs/T-042/momentum_closure_check.json
"""
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "work" / "lib"))
from extract_cfd_metrics import read_vtp, newell  # noqa: E402

VTK_DIR = REPO / "outputs" / "T-042" / "vtk_boundary_wss"
OUT = REPO / "outputs" / "T-042" / "momentum_closure_check.json"
PATCHES = ["nostril_L", "nostril_R", "nasopharynx_outlet", "wall"]
RHO = 1.2


def vec_add(a, b, s=1.0):
    return [a[i] + s * b[i] for i in range(3)]


def main():
    F_p = [0.0, 0.0, 0.0]
    F_m = [0.0, 0.0, 0.0]
    F_w = [0.0, 0.0, 0.0]
    F_w_mag = 0.0
    per_patch = {}

    for name in PATCHES:
        vtp = read_vtp(VTK_DIR / (name + ".vtp"))
        pts, faces, data = vtp["points"], vtp["faces"], vtp["cell_data"]
        fp = [0.0, 0.0, 0.0]
        fm = [0.0, 0.0, 0.0]
        fw = [0.0, 0.0, 0.0]
        n_wall_faces = 0
        for i, face in enumerate(faces):
            nv = newell([pts[j] for j in face])
            two_a = math.sqrt(sum(c * c for c in nv))
            if two_a == 0.0:
                continue
            area = 0.5 * two_a
            n = [c / two_a for c in nv]  # unit outward normal
            if "p" in data:
                p = data["p"][i] * RHO
                fp = vec_add(fp, [p * n[a] * area for a in range(3)])
            if "U" in data:
                U = data["U"][i]
                un = sum(U[a] * n[a] for a in range(3))
                fm = vec_add(fm, [RHO * U[a] * un * area for a in range(3)])
            if "wallShearStress" in data:
                t = data["wallShearStress"][i]
                fw = vec_add(fw, [t[a] * RHO * area for a in range(3)])
                F_w_mag += RHO * math.sqrt(sum(c * c for c in t)) * area
                n_wall_faces += 1
        per_patch[name] = {
            "pressure_force_N": fp, "momentum_flux_N": fm,
            "wall_shear_vector_N": fw,
            "faces_with_wss": n_wall_faces,
        }
        F_p = vec_add(F_p, fp)
        F_m = vec_add(F_m, fm)
        F_w = vec_add(F_w, fw)

    def norm(v):
        return math.sqrt(sum(c * c for c in v))

    # balance: -F_p + F_w_on_fluid = F_m  ->  F_w_on_fluid = F_m + F_p
    expected = vec_add(F_m, F_p)
    res_plus = [expected[a] - F_w[a] for a in range(3)]      # tau as force ON fluid
    res_minus = [expected[a] + F_w[a] for a in range(3)]     # tau as force BY fluid
    scale = norm(F_p)

    result = {
        "check": "steady whole-domain momentum closure, patient b15 maxh1 (T-041 arm)",
        "identity": "-F_p + F_w = F_m  (outward normals, rho=1.2, kinematic p and tau)",
        "F_pressure_N": F_p,
        "F_momentum_flux_N": F_m,
        "F_wall_shear_vector_N": F_w,
        "F_wall_shear_magnitude_integral_N": F_w_mag,
        "expected_wall_shear_N": expected,
        "residual_tau_on_fluid_N": res_plus,
        "residual_tau_by_fluid_N": res_minus,
        "closure_rel_to_Fp": {
            "tau_as_force_on_fluid": norm(res_plus) / scale,
            "tau_as_force_by_fluid": norm(res_minus) / scale,
        },
        "per_patch": per_patch,
        "caveats": [
            "closure/sanity check only, not a pass criterion",
            "field not fully converged (residualControl unmet; converged=false)",
            "discrete face integration; pressure-velocity coupling residual",
            "wall patch pressure axial contribution included via per-face p",
        ],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "F_p_N": F_p, "F_m_N": F_m, "F_w_vec_N": F_w,
        "F_w_mag_integral_N": F_w_mag,
        "closure_rel_to_Fp": result["closure_rel_to_Fp"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
