from Test.TestPane.layout import close_leaf, collect_leaves, find_leaf, find_neighbor, hit_test, layout, split_leaf
from Test.TestPane.model import Direction, Leaf, MoveDirection, Pane, Rect


def _root(width=9, height=7):
    root = Leaf(Pane("p1", "p1", Rect(0, 0, width, height)))
    layout(root, Rect(0, 0, width, height))
    return root


def test_single_pane_full_rect():
    root = _root(9, 7)
    pane = collect_leaves(root)[0]
    assert pane.rect == Rect(0, 0, 9, 7)


def test_vertical_split_even_width_gives_right_plus_one():
    root = _root(8, 5)
    root, new_id = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 8, 5))
    left = find_leaf(root, "p1").pane
    right = find_leaf(root, new_id).pane
    assert left.rect.w == 4
    assert right.rect.w == 5
    assert left.rect.right == right.rect.x


def test_horizontal_split_even_height_gives_bottom_plus_one():
    root = _root(7, 6)
    root, new_id = split_leaf(root, "p1", Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 7, 6))
    top = find_leaf(root, "p1").pane
    bottom = find_leaf(root, new_id).pane
    assert top.rect.h == 3
    assert bottom.rect.h == 4
    assert top.rect.bottom == bottom.rect.y


def test_nested_split_layout_shared_boundaries():
    root = _root(9, 7)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))
    root, p3 = split_leaf(root, p2, Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 9, 7))

    left = find_leaf(root, "p1").pane
    right_top = find_leaf(root, p2).pane
    right_bottom = find_leaf(root, p3).pane

    assert left.rect.right == right_top.rect.x
    assert right_top.rect.bottom == right_bottom.rect.y
    assert right_top.rect.x == right_bottom.rect.x


def test_split_rejected_when_too_small():
    root = _root(2, 5)
    new_root, new_id = split_leaf(root, "p1", Direction.VERTICAL)
    assert new_root is root
    assert new_id is None


def test_neighbor_left_right():
    root = _root(9, 7)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))
    assert find_neighbor(root, "p1", MoveDirection.RIGHT) == p2
    assert find_neighbor(root, p2, MoveDirection.LEFT) == "p1"


def test_neighbor_prefers_largest_overlap():
    root = _root(11, 9)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 11, 9))
    root, p3 = split_leaf(root, "p1", Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 11, 9))
    root, p4 = split_leaf(root, p2, Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 11, 9))

    assert find_neighbor(root, p3, MoveDirection.RIGHT) == p4


def test_close_two_pane_collapses_to_sibling():
    root = _root(9, 7)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))

    new_root, replacement = close_leaf(root, "p1")
    assert isinstance(new_root, Leaf)
    assert collect_leaves(new_root)[0].pane_id == p2
    assert collect_leaves(replacement)[0].pane_id == p2


def test_close_nested_returns_replacement_subtree():
    root = _root(9, 7)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))
    root, p3 = split_leaf(root, "p1", Direction.HORIZONTAL)
    layout(root, Rect(0, 0, 9, 7))

    new_root, replacement = close_leaf(root, "p1")
    ids = [pane.pane_id for pane in collect_leaves(new_root)]
    assert ids == [p3, p2]
    assert collect_leaves(replacement)[0].pane_id == p3


def test_hit_test_returns_interior_pane():
    root = _root(9, 7)
    root, p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))
    assert hit_test(root, 1, 1) == "p1"
    assert hit_test(root, 7, 1) == p2


def test_hit_test_ignores_shared_border():
    root = _root(9, 7)
    root, _p2 = split_leaf(root, "p1", Direction.VERTICAL)
    layout(root, Rect(0, 0, 9, 7))
    assert hit_test(root, 4, 2) is None
