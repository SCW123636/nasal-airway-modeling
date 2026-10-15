"""Analytic parent-edge answers, independent of triangulation details."""
import unittest
import numpy as np
from outlet_selection_lineage import SourceSelectorLineage


class LineageTests(unittest.TestCase):
    def test_mixed_edge_interpolates_delete_side_instead_of_or_and(self):
        p = np.array([[-2, 0, 0], [2, 0, 0], [2, 1, 0]], float)
        f = np.array([[0, 1, 2]])
        spec = {'point_lps_mm': [0, 0, 0], 'normal_lps': [1, 0, 0], 'keep_positive': True}
        lineage = SourceSelectorLineage(p, f, {'out': spec},
                                      {'out': np.array([True, False, False])}, 1e-7)
        lineage.append_intersection(0, 1, [-1, 0, 0])
        lineage.append_intersection(0, 1, [1, 0, 0])
        lineage.append_intersection(0, 1, [0, 0, 0])
        np.testing.assert_array_equal(lineage.get('out'), [True, False, False, True, False, False])

    def test_kept_side_semantics_follow_keep_positive(self):
        p = np.array([[-2, 0, 0], [2, 0, 0], [2, 1, 0]], float)
        spec = {'point_lps_mm': [0, 0, 0], 'normal_lps': [1, 0, 0], 'keep_positive': False}
        lineage = SourceSelectorLineage(p, np.array([[0, 1, 2]]), {'out': spec},
                                      {'out': np.array([False, True, True])}, 1e-7)
        lineage.append_intersection(0, 1, [1, 0, 0])
        self.assertTrue(lineage.get('out')[-1])

    def test_new_cap_edge_with_mixed_negative_membership_refuses(self):
        p = np.array([[-2, 0, 0], [-2, 1, 0], [-2, 2, 0],
                      [-2, 10, 0], [-2, 11, 0], [-2, 12, 0]], float)
        f = np.array([[0, 1, 2], [3, 4, 5]])
        spec = {'point_lps_mm': [0, 0, 0], 'normal_lps': [1, 0, 0], 'keep_positive': True}
        lineage = SourceSelectorLineage(p, f, {'out': spec},
                                      {'out': np.array([True, True, True, False, False, False])}, 1e-7)
        with self.assertRaisesRegex(ValueError, 'ambiguous selector lineage'):
            lineage.append_intersection(0, 3, [-2, 5, 0])


if __name__ == '__main__':
    unittest.main()
