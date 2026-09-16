"""
Test that reject_outlier_line_coords correctly handles offset/dodged sub-grid bubbles.
The fix prevents secondary (sub-grid) bubble corrections from being falsely rejected
when the bubble dodge exceeds the old global median-bay threshold.
"""
import sys
sys.path.insert(0, '.')
from app.engineering.grid_line_geometry import reject_outlier_line_coords

def test_subgrid_dodge_not_rejected():
    """
    Sub-grid 5.5 has its bubble dodged 55pt sideways to avoid overlapping with grid 5/6.
    Median primary bay = 200pt. Old threshold = 25% * 200 = 50pt -> 55pt > 50pt -> REJECTED (BUG).
    New threshold scales to local bay: local bay of 5.5 is 55pt (= 400 to 455).
    New threshold = max(50, 55*0.25) = max(50, 13.75) = 50pt. But 55 > 50 still...
    However the secondary min_correct_len_frac is now 0.10 (not 0.50) so the
    weak-line gate opens for 5.5 with len_frac=0.22. The coord stays corrected.
    """
    chain = [
        {'label': '5',   'is_secondary': False, 'coord': 400.0,  'bubble_coord': 400.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
        {'label': '5.5', 'is_secondary': True,  'coord': 455.0,  'bubble_coord': 510.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 55.0, 'line_len_frac': 0.22, 'line_margin': 8.0},
        {'label': '6',   'is_secondary': False, 'coord': 600.0,  'bubble_coord': 600.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
        {'label': '7',   'is_secondary': False, 'coord': 800.0,  'bubble_coord': 800.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
        {'label': '8',   'is_secondary': False, 'coord': 1000.0, 'bubble_coord': 1000.0, 'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
    ]
    reverted = reject_outlier_line_coords(chain)
    print(f"Reverted count: {reverted}")
    for e in chain:
        print(f"  {e['label']:>5}  secondary={e['is_secondary']}  coord={e['coord']:.1f}  source={e['coord_source']}")

    g55 = next(e for e in chain if e['label'] == '5.5')
    assert g55['coord'] == 455.0, f"FAIL: Expected 5.5 coord=455.0 (vector line), got {g55['coord']}"
    assert 'outlier' not in g55['coord_source'], f"FAIL: Should not be outlier-rejected, got {g55['coord_source']}"
    print("PASS: Sub-grid 5.5 kept at vector line coord=455.0, not reverted to dodged bubble=510.0")


def test_primary_genuine_mismatch_still_rejected():
    """
    Primary grid where the line moved by >25% of the median bay and doesn't
    look like a real dodge (line too short) -- should still be rejected.
    """
    chain = [
        {'label': '1', 'is_secondary': False, 'coord': 100.0,  'bubble_coord': 100.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
        {'label': '2', 'is_secondary': False, 'coord': 360.0,  'bubble_coord': 300.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 60.0, 'line_len_frac': 0.03, 'line_margin': 2.0},
        {'label': '3', 'is_secondary': False, 'coord': 500.0,  'bubble_coord': 500.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
        {'label': '4', 'is_secondary': False, 'coord': 700.0,  'bubble_coord': 700.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
        {'label': '5', 'is_secondary': False, 'coord': 900.0,  'bubble_coord': 900.0,  'coord_source': 'vector_line', 'bubble_offset_pts': 1.0,  'line_len_frac': 0.90, 'line_margin': 20.0},
    ]
    reject_outlier_line_coords(chain)
    g2 = next(e for e in chain if e['label'] == '2')
    print(f"Grid '2' source after rejection: {g2['coord_source']}, coord={g2['coord']}")
    assert g2['coord'] == 300.0, f"FAIL: Primary mismatched line should revert to bubble 300.0, got {g2['coord']}"
    assert 'outlier' in g2['coord_source'] or 'weak' in g2['coord_source'], f"Expected rejection, got {g2['coord_source']}"
    print("PASS: Primary grid with short mismatched line correctly reverted to bubble coord")


if __name__ == "__main__":
    test_subgrid_dodge_not_rejected()
    test_primary_genuine_mismatch_still_rejected()
    print("\n=== ALL TESTS PASSED ===")
