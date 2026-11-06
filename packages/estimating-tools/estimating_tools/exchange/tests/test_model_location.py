from __future__ import annotations


def test_the_read_model_lives_in_exchange(doc):
    from estimating_tools.exchange import model
    wb = model.parse(doc)
    assert [i.id for i in wb.items] == [1, 4, 2, 3, 5]
    # Item 1 sits in section 1, which heads item 1's schedule (1).
    item = wb.items[0]
    assert item.section_id == 1 and item.schedule_id == 1
    assert model.section_of(wb, item).id == item.section_id
    # Item 4 has no section at all.
    loose = next(i for i in wb.items if i.id == 4)
    assert loose.section_id is None and model.section_of(wb, loose) is None

