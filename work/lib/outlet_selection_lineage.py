"""Transport source negative-component selectors across edge subdivisions.

This preserves a source selection; it neither rediscovers anatomy nor floods
the modified mesh. A selected source vertex must be on the delete side, and
selection cannot change along an edge wholly on that side. Those are the
contracts of connectivity_opened_surface.flood_mask.
"""
import numpy as np


def signed_distance(points, spec, tolerance_mm):
    origin = np.asarray(spec.get('point_lps_mm'), dtype=float)
    normal = np.asarray(spec.get('normal_lps'), dtype=float)
    if (origin.shape != (3,) or normal.shape != (3,)
            or not np.isfinite(origin).all() or not np.isfinite(normal).all()
            or np.linalg.norm(normal) < 1e-12 or type(spec.get('keep_positive')) is not bool):
        raise ValueError('Invalid selector clipping plane')
    normal = normal / np.linalg.norm(normal)
    if not spec['keep_positive']:
        normal = -normal
    values = (np.asarray(points, dtype=float) - origin) @ normal
    values[np.abs(values) <= tolerance_mm] = 0
    return values


class SourceSelectorLineage:
    """Exact source-length masks plus append-only parent-edge inheritance."""
    def __init__(self, points, faces, planes, selectors, tolerance_mm):
        self.tolerance_mm = tolerance_mm
        self.planes = planes
        self.masks = {}
        self.signed = {}
        edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
        for name, raw in selectors.items():
            if name not in planes:
                raise ValueError(name + ': selector has no clipping plane')
            mask = np.asarray(raw)
            if mask.ndim != 1 or len(mask) != len(points) or mask.dtype.kind != 'b':
                raise ValueError(name + ': selector must be boolean with exactly one value per source vertex')
            signed = signed_distance(points, planes[name], tolerance_mm)
            if np.any(mask & (signed >= 0)):
                raise ValueError(name + ': selector contains a vertex outside the strict delete halfspace')
            negative_edges = edges[(signed[edges] < 0).all(axis=1)]
            if np.any(mask[negative_edges[:, 0]] != mask[negative_edges[:, 1]]):
                raise ValueError(name + ': ambiguous selector changes across a wholly negative source edge')
            self.masks[name] = mask.tolist()
            self.signed[name] = signed.tolist()

    def get(self, name):
        values = self.masks.get(name)
        return None if values is None else np.asarray(values, dtype=bool)

    def append_intersection(self, a, b, point):
        """Derive membership from parent edge and each selector's own plane.

        On a mixed-sign parent edge the negative portion has its negative
        parent's membership. With two negative parents membership must agree;
        disagreement is ambiguous and is rejected instead of choosing OR/AND.
        A point on the selector plane is kept and never a delete seed.
        """
        for name, values in self.masks.items():
            signed = self.signed[name]
            value = float(signed_distance(np.asarray([point]), self.planes[name], self.tolerance_mm)[0])
            if value >= 0:
                selected = False
            else:
                parents = [i for i in (a, b) if signed[i] < 0]
                if not parents or len({values[i] for i in parents}) != 1:
                    raise ValueError(name + ': ambiguous selector lineage on a subdivided edge')
                selected = values[parents[0]]
            values.append(bool(selected))
            signed.append(value)
