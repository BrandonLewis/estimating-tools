from __future__ import annotations

import pytest

from estimating_tools.heavycivil import formulas as F


def test_qualified_quotes_and_escapes():
    assert F.qualified("Cost Report", "M", 12) == "'Cost Report'!$M$12"
    assert F.qualified("O'Neil", "A", 1) == "'O''Neil'!$A$1"


def test_multiplier_root_and_child():
    assert F.multiplier(7, None) == "=K7"
    assert F.multiplier(9, 7) == "=K9*AA7"


def test_activity_split_without_resources_is_zero_times_multiplier():
    assert F.activity_split("N", 7, None) == "=0*AA7"
    assert F.activity_split("N", 7, (8, 10)) == "=SUM(N8:N10)*AA7"


def test_activity_labor_crew_priced_uses_crew_cells():
    crew_cells = {"rate": "Crews!$J$5", "hps": "Crews!$G$5", "factor": "Crews!$H$5",
                  "headcount": "Crews!$I$5"}
    f = F.activity_labor(7, (8, 9), crew_cells=crew_cells, missing_crew=False)
    assert f == '=IF(J7<>"",Crews!$J$5*J7*Crews!$G$5*Crews!$H$5,SUM(M8:M9))*AA7'


def test_activity_labor_missing_crew_uses_export_value():
    f = F.activity_labor(7, None, crew_cells=None, missing_crew=True)
    assert f == '=IF(J7<>"",AH7*J7,0)*AA7'


def test_resource_cost_has_every_rule():
    f = F.resource_cost(12)
    for piece in ('S12="labor"', 'T12="flat"', 'AF12=""', "INDEX($I:$I,MAX(AJ12,1))", 'V12<>"Y"',
                  "U12/100", "C12*E12"):
        assert piece in f


def test_resource_formulas_find_their_activity_by_position():
    """No fixed activity row: production, production unit, hours/shift and
    crew factor are read through the row's AJ (the nearest ACTIVITY)."""
    units = F.resource_units(12)
    for piece in ("INDEX($F:$F,MAX(AJ12,1))", "INDEX($G:$G,MAX(AJ12,1))",
                  "INDEX($H:$H,MAX(AJ12,1))"):
        assert piece in units
    assert "INDEX($I:$I,MAX(AJ12,1))" in F.resource_cost(12)
    assert isinstance(units, F.Formula)


def test_activity_row_chains_from_the_row_above():
    # Every row, the first included, anchors at the header row: a range
    # whose first row is data would break when that row is deleted.
    assert F.activity_row(5, 4) == '=IF(W5="ACTIVITY",ROW(),MAX(AJ$4:AJ4))'
    assert F.activity_row(9, 4) == '=IF(W9="ACTIVITY",ROW(),MAX(AJ$4:AJ8))'


def test_item_cost_handles_manual_excluded_and_zero_quantity():
    f = F.item_cost(5)
    assert f.startswith('=IF(OR(AG5="",AG5=0),0,')
    assert "AB5" not in f   # an excluded item prices from AI too, not the stored total
    assert 'E5<>""' in f and "AI5*AG5" in f


def test_share_total_rounds_only_split_shares():
    assert F.share_total(2, 7, "Cost Report", split=False) == "='Cost Report'!$R$7*C2"
    assert F.share_total(2, 7, "Cost Report", split=True) == "=ROUND('Cost Report'!$R$7*C2,2)"


def test_bid_unit_price_shape():
    f = F.bid_unit_price(13)
    assert f.startswith('=IF(OR(F13="excluded",P13=0,D13="",D13=0),"",')
    assert 'IF(G13<>"",G13,ROUND(N13*$C$9/D13,2))' in f
    assert isinstance(f, F.Formula)


def test_bid_total_amount_uses_schedule_sumifs():
    f = F.bid_total_amount(schedule_ids=(1, 2), includes_unscheduled=True, first=13, last=20)
    assert f == "=SUMIF(M13:M20,1,I13:I20)+SUMIF(M13:M20,2,I13:I20)+SUMIF(M13:M20,-1,I13:I20)"
    assert F.bid_total_amount(schedule_ids=None, includes_unscheduled=True, first=13, last=20) \
        == "=SUM(I13:I20)"
    # Every schedule but not the unscheduled items (EstimateBidTotal.covers).
    assert F.bid_total_amount(schedule_ids=None, includes_unscheduled=False, first=13, last=20) \
        == "=SUM(I13:I20)-SUMIF(M13:M20,-1,I13:I20)"
    assert F.bid_total_amount(schedule_ids=(), includes_unscheduled=False, first=13, last=20) \
        == "=0"


def test_bid_estimate_figures_reference_the_input_block():
    assert F.bid_direct_cost(13, 20) == "=ROUND(SUM(Q13:Q20),2)"
    assert F.bid_markup_total() == "=ROUND((C7+C6)*C4/100+C5,2)"
    assert F.bid_factor() == "=IF(C7<=0,1,(C7+C6+C8)/C7)"
    assert F.bid_excluded_cost(13, 20) == '=ROUND(SUMIF(F13:F20,"excluded",N13:N20),2)'


def test_bid_priced_reads_the_manual_or_calculated_price():
    # An item excluded at export carries its export calculated price in AI.
    assert F.bid_priced("Cost Report", 5) == \
        "=IF(OR('Cost Report'!$E$5<>\"\",'Cost Report'!$AI$5<>\"\"),1,0)"


def test_schedule_finish_shifts_by_whole_working_days():
    f = F.schedule_finish(5, "_cal", 900)
    assert "MATCH(I5,'_cal'!$A$1:$A$900,1)" in f
    # Against the export's extended duration: per pass (J) x multiplier (K).
    assert "CEILING(E5,1)-CEILING(J5*K5,1)" in f
    # Clamped to the calendar's last row rather than erroring to the export.
    assert "INDEX('_cal'!$A$1:$A$900,MIN(900," in f
    assert isinstance(f, F.Formula)


def test_schedule_duration_uses_shifts_else_export():
    assert F.schedule_duration(5, "Cost Report", 7) == \
        "=IF('Cost Report'!$J$7<>\"\",'Cost Report'!$J$7,J5)*'Cost Report'!$AA$7"


def test_flat_resource_skips_crew_priced_labour():
    f = F.flat_resource_cost("Cost Report", 9, 7)
    assert f.startswith("=IF(AND('Cost Report'!$S$9=\"labor\",AND(")
    assert "'Cost Report'!$AG$9*'Cost Report'!$AA$7" in f


def test_recap_and_column_sum_handle_empty_ranges():
    assert F.recap_manhours(5, "Cost Report", "_shares", 2, 1) == "=0"
    assert F.column_sum("F", 5, 4) == "=0"
    assert F.column_sum("F", 5, 9) == "=SUM(F5:F9)"


def test_bid_total_amount_coerces_each_schedule_id_to_an_integer():
    f = F.bid_total_amount(schedule_ids=(3, 12), includes_unscheduled=False, first=13, last=20)
    assert f == "=SUMIF(M13:M20,3,I13:I20)+SUMIF(M13:M20,12,I13:I20)"
    # Defence in depth behind model.parse: a non-integer never reaches the text.
    with pytest.raises((TypeError, ValueError)):
        F.bid_total_amount(schedule_ids=('1)+HYPERLINK("http://x","y"',),
                           includes_unscheduled=False, first=13, last=20)


def test_step_shifts_sum_the_bracketed_range():
    f = F.step_shifts(20, (21, 23))
    total = ('SUMIF(D21:D23,"HOURS",C21:C23)/IF(OR(H20="",H20=0),8,H20)'
             '+SUMIF(D21:D23,"<>HOURS",C21:C23)')
    assert f == (f"=IF(ABS(MOD(({total})*100,1)-0.5)<1E-9,"
                 f"(INT(({total})*100)+MOD(INT(({total})*100),2))/100,ROUND({total},2))")


def test_crew_sum_spans_the_crew_block():
    assert F.crew_sum("C", (5, 8)) == "=SUM(C5:C8)"


def test_resource_formulas_survive_a_blank_activity_row():
    """AJ is 0 above the first activity; INDEX(..., 0) would return a whole
    column, so the lookup clamps to row 1."""
    assert "INDEX($F:$F,MAX(AJ12,1))" in F.resource_units(12)
