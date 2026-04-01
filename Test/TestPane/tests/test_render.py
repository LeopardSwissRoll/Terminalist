from Test.TestPane.layout import collect_leaves, layout, split_leaf
from Test.TestPane.model import Direction, Leaf, Pane, Rect
from Test.TestPane.render import D, L, R, U, build_border_grid, compose, frame_to_plain_text


def _root(width=9, height=7):
    root = Leaf(Pane("p1", "p1", Rect(0, 0, width, height)))
    layout(root, Rect(0, 0, width, height))
    return root


def test_root_outer_border_corners_render():
    root = _root(5, 4)
    frame = compose(root, "p1", 5, 4)
    assert frame[0][0].ch == "┌"
    assert frame[0][4].ch == "┐"
    assert frame[3][0].ch == "└"
    assert frame[3][4].ch == "┘"


def test_internal_vertical_border_forms_t_junctions():
    root = _root(8, 5)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 8, 5))
    frame = compose(root, p2, 8, 5)
    assert frame[0][3].ch == "┬"
    assert frame[4][3].ch == "┴"
    assert frame[2][3].ch == "│"


def test_complete_cross_renders_center_plus():
    root = _root(9, 7)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))
    root, p3 = split_leaf(root, "p1", Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 9, 7))
    root, p4 = split_leaf(root, p2, Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 9, 7))

    frame = compose(root, p4, 9, 7)
    assert frame[3][4].ch == "┼"


def test_owner_sets_distinguish_outer_and_inner_borders():
    root = _root(8, 5)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 8, 5))
    grid = build_border_grid(root, 8, 5)
    assert grid[0][0].owners == frozenset({"p1"})
    assert grid[2][3].owners == frozenset({"p1", p2})


def test_only_focused_border_cells_are_active():
    root = _root(8, 5)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 8, 5))
    frame = compose(root, p2, 8, 5)
    assert frame[2][3].style == "border_active"
    assert frame[2][0].style == "border_inactive"
    assert frame[2][7].style == "border_active"


def test_focused_and_unfocused_fill_and_label_styles():
    root = _root(8, 5)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 8, 5))
    frame = compose(root, p2, 8, 5)

    focused_interior = frame[2][5]
    unfocused_interior = frame[2][1]
    assert focused_interior.style in {"fill_active", "label_active"}
    assert unfocused_interior.style in {"fill_inactive", "label_inactive"}


def test_corner_mask_values_are_not_crosses():
    root = _root(5, 4)
    grid = build_border_grid(root, 5, 4)
    assert grid[0][0].mask == (D | R)
    assert grid[0][4].mask == (D | L)
    assert grid[3][0].mask == (U | R)
    assert grid[3][4].mask == (U | L)


def test_frame_to_plain_text_exports_visible_buffer():
    root = _root(5, 4)
    frame = compose(root, "p1", 5, 4)
    text = frame_to_plain_text(frame)
    assert "┌" in text
    assert "P1" in text
