# Copyright (c) 2026, Profezzo and Contributors
# See license.txt
"""A weighment has two bag tables. Both take their rows from one place, chosen in this order:

1. Quality Check accepted (Accepted / Partially Accepted) with lines: the QC lines;
2. otherwise the RST bags, when the RST has any;
3. otherwise one row with 0.

- Bag Type (bag_weight_details): Jute / Plastic, Total = Jute + Plastic.
- Bag Condition (old_new_bags): Old / New (the same bags, split another way; not added to Total).

The GRN Note copies both from the weighment. Mocked tests: no site, no database.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe

from ivri_od.procurement.doctype.grn_note import grn_note as grn_module
from ivri_od.procurement.doctype.weigh_bridge_measurement.weigh_bridge_measurement import (
	WeighBridgeMeasurement,
	_ensure_wbm_bag_details_from_qc,
	build_wbm_bag_rows,
	build_wbm_condition_rows,
	unlink_quality_check_from_weigh_bridge,
)

MODULE = "ivri_od.procurement.doctype.weigh_bridge_measurement.weigh_bridge_measurement"
ZERO_TYPE = [(0, 0, 0)]
ZERO_CONDITION = [(0, 0)]


def row(jute=0, plastic=0):
	return SimpleNamespace(jute_bags=jute, plastic_bags=plastic, total_bags=jute + plastic)


def type_counts(rows):
	return [(_get(r, "jute_bags"), _get(r, "plastic_bags"), _get(r, "total_bags")) for r in rows]


def condition_counts(rows):
	return [(_get(r, "old_bags"), _get(r, "new_bags")) for r in rows]


def _get(r, k):
	return r[k] if isinstance(r, dict) else getattr(r, k)


class _Wbm:
	"""Just enough of a Weigh Bridge Measurement for the bag table methods."""

	def __init__(self, quality_check="", rows=(), rst="", condition=()):
		self.quality_check = quality_check
		self.demo_rst_data = rst
		self.bag_weight_details = list(rows)
		self.old_new_bags = list(condition)
		self.total_bags = sum(r.total_bags for r in rows)
		self.flags = SimpleNamespace()
		self.save = MagicMock()

	def get(self, key):
		return getattr(self, key, None)

	def append(self, fieldname, values):
		new = SimpleNamespace(**values)
		getattr(self, fieldname).append(new)
		return new

	_sync_bag_details_from_qc = WeighBridgeMeasurement._sync_bag_details_from_qc
	_persist_bag_details_from_qc = WeighBridgeMeasurement._persist_bag_details_from_qc
	_sync_total_bags_from_qc_table = WeighBridgeMeasurement._sync_total_bags_from_qc_table
	_total_bags_from_qc_table = WeighBridgeMeasurement._total_bags_from_qc_table


class _NoSite(unittest.TestCase):
	"""Fake database: a QC decision, the QC lines of both tables, and the RST bag fields."""

	def setUp(self):
		frappe.local.lang = "en"
		self.decision = ""
		self.rst = None  # dict of RST bag fields, or None when there is no RST
		self.db = MagicMock()
		self.db.exists.side_effect = lambda doctype, name=None: self.rst is not None if doctype == "RST Details" else True
		self.db.has_column.return_value = True
		self.db.get_value.side_effect = self._get_value
		for patcher in (
			patch.object(frappe, "db", self.db, create=True),
			# frappe.flt needs a site (it reads system settings); plain rounding is enough here
			patch(f"{MODULE}._trim_qty", side_effect=lambda v, d=3: round(float(v or 0), d)),
		):
			patcher.start()
			self.addCleanup(patcher.stop)
		self.qc_lines()
		self.qc_condition()

	def _get_value(self, doctype, name, fields=None, as_dict=False, **kwargs):
		if doctype == "Quality Check":
			return self.decision
		if doctype == "RST Details":
			return frappe._dict(self.rst or {})
		return None

	def _patch(self, target, value):
		patcher = patch(target, return_value=value)
		patcher.start()
		self.addCleanup(patcher.stop)

	def qc_lines(self, *lines):
		"""Bag Type lines of the Quality Check, as (jute, plastic)."""
		self._patch(f"{MODULE}._qc_bag_lines", [{"jute_pkt_no": j, "no_of_plastic_bag": p} for j, p in lines])

	def qc_condition(self, *lines):
		"""Bag Condition lines of the Quality Check, as (old, new)."""
		self._patch(f"{MODULE}._qc_condition_lines", [{"old_bags": o, "new_bags": n} for o, n in lines])


class TestBagTypeRule(_NoSite):
	def test_accepted_qc_gives_its_lines(self):
		self.decision = "Accepted"
		self.qc_lines((120, 48), (10, 0))
		self.rst = {"jute_bags": 5, "plastic_bags": 5}  # ignored: QC wins
		self.assertEqual(type_counts(build_wbm_bag_rows("QC-1", "RST-1")), [(120, 48, 168), (10, 0, 10)])

	def test_partially_accepted_qc_counts_as_accepted(self):
		self.decision = "Partially Accepted"
		self.qc_lines((0, 196))
		self.assertEqual(type_counts(build_wbm_bag_rows("QC-1", "")), [(0, 196, 196)])

	def test_qc_not_accepted_takes_the_rst_bags(self):
		self.qc_lines((120, 48))  # QC saved but no decision yet
		self.rst = {"jute_bags": 100, "plastic_bags": 20}
		self.assertEqual(type_counts(build_wbm_bag_rows("QC-1", "RST-1")), [(100, 20, 120)])

	def test_accepted_qc_without_lines_falls_back_to_the_rst(self):
		self.decision = "Accepted"
		self.rst = {"jute_bags": 7, "plastic_bags": 0}
		self.assertEqual(type_counts(build_wbm_bag_rows("QC-1", "RST-1")), [(7, 0, 7)])

	def test_rst_without_bags_gives_one_zero_row(self):
		self.rst = {"jute_bags": 0, "plastic_bags": 0}
		self.assertEqual(type_counts(build_wbm_bag_rows("", "RST-1")), ZERO_TYPE)

	def test_no_qc_and_no_rst_gives_one_zero_row(self):
		self.assertEqual(type_counts(build_wbm_bag_rows("", "")), ZERO_TYPE)


class TestBagConditionRule(_NoSite):
	def test_accepted_qc_gives_its_old_and_new(self):
		self.decision = "Accepted"
		self.qc_condition((250, 50))
		self.rst = {"old_bags": 1, "new_bags": 1}  # ignored: QC wins
		self.assertEqual(condition_counts(build_wbm_condition_rows("QC-1", "RST-1")), [(250, 50)])

	def test_qc_not_accepted_takes_the_rst_old_and_new(self):
		self.qc_condition((250, 50))
		self.rst = {"old_bags": 90, "new_bags": 30}
		self.assertEqual(condition_counts(build_wbm_condition_rows("QC-1", "RST-1")), [(90, 30)])

	def test_rst_with_only_new_bags(self):
		self.rst = {"old_bags": 0, "new_bags": 40}
		self.assertEqual(condition_counts(build_wbm_condition_rows("", "RST-1")), [(0, 40)])

	def test_nothing_known_gives_one_zero_row(self):
		self.rst = {"old_bags": 0, "new_bags": 0}
		self.assertEqual(condition_counts(build_wbm_condition_rows("", "RST-1")), ZERO_CONDITION)
		self.assertEqual(condition_counts(build_wbm_condition_rows("", "")), ZERO_CONDITION)


class TestWeighmentSave(_NoSite):
	def test_save_fills_both_tables_and_total_is_jute_plus_plastic(self):
		self.rst = {"jute_bags": 100, "plastic_bags": 20, "old_bags": 90, "new_bags": 30}
		wbm = _Wbm("", [], rst="RST-1")
		wbm._sync_bag_details_from_qc()
		self.assertEqual(type_counts(wbm.bag_weight_details), [(100, 20, 120)])
		self.assertEqual(condition_counts(wbm.old_new_bags), [(90, 30)])
		self.assertEqual(wbm.total_bags, 120)

	def test_qc_accepted_later_replaces_the_rst_rows(self):
		self.rst = {"jute_bags": 100, "plastic_bags": 0, "old_bags": 100, "new_bags": 0}
		wbm = _Wbm("", [], rst="RST-1")
		wbm._sync_bag_details_from_qc()
		self.decision = "Accepted"
		self.qc_lines((90, 12))
		self.qc_condition((60, 42))
		wbm.quality_check = "QC-9"
		wbm._sync_bag_details_from_qc()
		self.assertEqual(type_counts(wbm.bag_weight_details), [(90, 12, 102)])
		self.assertEqual(condition_counts(wbm.old_new_bags), [(60, 42)])
		self.assertEqual(wbm.total_bags, 102)

	def test_rows_that_already_match_are_kept(self):
		self.rst = {"jute_bags": 10, "plastic_bags": 0, "old_bags": 10, "new_bags": 0}
		existing, existing_condition = row(10, 0), SimpleNamespace(old_bags=10, new_bags=0)
		wbm = _Wbm("", [existing], rst="RST-1", condition=[existing_condition])
		wbm._sync_bag_details_from_qc()
		self.assertIs(wbm.bag_weight_details[0], existing)
		self.assertIs(wbm.old_new_bags[0], existing_condition)

	def test_a_row_saved_with_an_old_total_is_rewritten(self):
		self.rst = {"jute_bags": 50, "plastic_bags": 50}
		stale = SimpleNamespace(jute_bags=50, plastic_bags=50, total_bags=150)  # old formula added Old Bags
		wbm = _Wbm("", [stale], rst="RST-1")
		wbm._sync_bag_details_from_qc()
		self.assertEqual(type_counts(wbm.bag_weight_details), [(50, 50, 100)])

	def test_stale_qc_rows_go_back_to_zero_when_nothing_is_known(self):
		wbm = _Wbm("", [row(150, 0)], condition=[SimpleNamespace(old_bags=150, new_bags=0)])
		wbm._sync_bag_details_from_qc()
		self.assertEqual(type_counts(wbm.bag_weight_details), ZERO_TYPE)
		self.assertEqual(condition_counts(wbm.old_new_bags), ZERO_CONDITION)
		self.assertEqual(wbm.total_bags, 0)

	def test_persist_writes_without_validate(self):
		self.decision = "Accepted"
		self.qc_lines((10, 5))
		wbm = _Wbm("QC-1")
		wbm._persist_bag_details_from_qc()
		self.assertEqual(wbm.total_bags, 15)
		wbm.save.assert_called_once_with(ignore_permissions=True)
		self.assertTrue(wbm.flags.ignore_validate)


class TestEnsureBagDetails(_NoSite):
	"""Background sync (QC saved / moved): rewrites only when a saved table differs from the rule."""

	def setUp(self):
		super().setUp()
		self.doc = MagicMock()
		self.saved = frappe._dict(quality_check="", demo_rst_data="")
		self.db.get_value.side_effect = self._get_value_ensure
		self.tables = {"Weigh Bridge Bag Detail": [], "Quality Check Old New Bag Detail": []}
		for target, kwargs in (
			("frappe.get_doc", {"return_value": self.doc}),
			("frappe.get_all", {"side_effect": lambda doctype, **kw: self.tables[doctype]}),
		):
			patcher = patch(target, **kwargs)
			patcher.start()
			self.addCleanup(patcher.stop)

	def _get_value_ensure(self, doctype, name, fields=None, as_dict=False, **kwargs):
		if doctype == "Weigh Bridge Measurement":
			return self.saved if as_dict else self.saved.get(fields)
		return self._get_value(doctype, name, fields, as_dict)

	def _ensure(self, bag_type, condition, qc=""):
		self.tables["Weigh Bridge Bag Detail"] = [frappe._dict(jute_bags=j, plastic_bags=p, total_bags=j + p) for j, p in bag_type]
		self.tables["Quality Check Old New Bag Detail"] = [frappe._dict(old_bags=o, new_bags=n) for o, n in condition]
		_ensure_wbm_bag_details_from_qc("WBM-1", {"quality_check": qc})

	def test_matching_tables_are_left_alone(self):
		self.saved.update(quality_check="QC-1")
		self.decision = "Accepted"
		self.qc_lines((120, 48))
		self.qc_condition((100, 68))
		self._ensure([(120, 48)], [(100, 68)], "QC-1")
		self.doc._persist_bag_details_from_qc.assert_not_called()

	def test_a_different_bag_type_is_rewritten(self):
		self.saved.update(quality_check="QC-1")
		self.decision = "Accepted"
		self.qc_lines((150, 0))
		self._ensure([(0, 168)], [(0, 0)], "QC-1")
		self.doc._persist_bag_details_from_qc.assert_called_once()

	def test_a_different_bag_condition_is_rewritten(self):
		self.saved.update(demo_rst_data="RST-1")
		self.rst = {"jute_bags": 0, "plastic_bags": 0, "old_bags": 5, "new_bags": 0}
		self._ensure([(0, 0)], [(0, 0)])
		self.doc._persist_bag_details_from_qc.assert_called_once()

	def test_empty_tables_get_the_zero_rows(self):
		self._ensure([], [])
		self.doc._persist_bag_details_from_qc.assert_called_once()

	def test_zero_rows_that_are_already_there_are_left_alone(self):
		self._ensure([(0, 0)], [(0, 0)])
		self.doc._persist_bag_details_from_qc.assert_not_called()

	def test_a_lookup_that_finds_no_qc_does_not_override_a_weighment_that_is_still_linked(self):
		self.saved.update(quality_check="QC-1")
		self._ensure([(150, 0)], [(0, 0)], "")
		self.doc._persist_bag_details_from_qc.assert_not_called()


class TestQcMovedToAnotherVisit(_NoSite):
	def test_the_old_weighments_are_resynced_before_weights_are_recalculated(self):
		order = MagicMock()
		with patch("frappe.get_all", return_value=["WBM-1"]), patch(f"{MODULE}._ensure_wbm_bag_details_from_qc", order.ensure), \
			patch(f"{MODULE}.persist_wbm_quality_and_net_after_qc_sync", order.net), \
			patch(f"{MODULE}._ensure_grn_note_for_weigh_bridge", order.grn):
			self.db.set_value = order.set_value
			result = unlink_quality_check_from_weigh_bridge("QC-1", "GE-NEW")
		self.assertEqual(result, ["WBM-1"])
		self.assertEqual([c[0] for c in order.mock_calls], ["set_value", "ensure", "net", "grn"])
		self.assertEqual(order.ensure.call_args, call("WBM-1", {"quality_check": "", "bag_details": []}))


class TestGrnCopiesFromWeighment(unittest.TestCase):
	def setUp(self):
		db = MagicMock()
		db.exists.return_value = True
		patcher = patch.object(frappe, "db", db, create=True)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_grn_total_is_jute_plus_plastic(self):
		rows = [frappe._dict(jute_bags=100, plastic_bags=20)]
		with patch("frappe.get_all", return_value=rows):
			self.assertEqual(grn_module._wbm_bag_counts_from_child_table("WBM-1"), (100, 20, 120))

	def test_grn_bag_condition_comes_from_the_weighment_even_without_qc(self):
		grn = SimpleNamespace(old_new_bags=["stale"], weigh_bridge_measurement="WBM-1")
		grn.append = lambda f, v: getattr(grn, f).append(v)
		rows = [frappe._dict(old_bags=90, new_bags=30)]
		with patch("frappe.get_all", return_value=rows) as get_all:
			grn_module.GRNNote._apply_wbm_bag_condition(grn, "WBM-1")
		self.assertEqual(grn.old_new_bags, [{"old_bags": 90, "new_bags": 30}])
		self.assertEqual(get_all.call_args.kwargs["filters"]["parenttype"], "Weigh Bridge Measurement")


class TestFormFields(unittest.TestCase):
	def setUp(self):
		import json
		from pathlib import Path

		base = Path(__file__).resolve().parents[1] / "doctype"

		def load(p):
			data = json.loads((base / p).read_text())
			return {f["fieldname"]: f for f in data["fields"]}, data["field_order"]

		self.wbm, self.wbm_order = load("weigh_bridge_measurement/weigh_bridge_measurement.json")
		self.child, _ = load("weigh_bridge_bag_detail/weigh_bridge_bag_detail.json")
		self.grn, _ = load("grn_note/grn_note.json")
		self.rst, self.rst_order = load("rst_details/rst_details.json")
		self.qc, _ = load("quality_check/quality_check.json")

	def test_weighment_has_bag_type_then_bag_condition(self):
		bag_type, condition = self.wbm["bag_weight_details"], self.wbm["old_new_bags"]
		self.assertEqual((bag_type["label"], bag_type["options"], bag_type.get("read_only")), ("Bag Type", "Weigh Bridge Bag Detail", 1))
		self.assertEqual(
			(condition["label"], condition["options"], condition.get("read_only")),
			("Paddy Type (In Bags)", "Quality Check Old New Bag Detail", 1),
		)
		self.assertLess(self.wbm_order.index("bag_weight_details"), self.wbm_order.index("old_new_bags"))
		for table in (bag_type, condition):
			self.assertNotIn("depends_on", table)
			self.assertNotIn("hidden", table)

	def test_bag_type_rows_are_jute_plastic_total(self):
		self.assertNotIn("old_bags", self.child)
		for name in ("jute_bags", "plastic_bags", "total_bags"):
			self.assertEqual((self.child[name].get("in_list_view"), self.child[name].get("read_only")), (1, 1), name)

	def test_rst_has_new_bags_after_old_bags(self):
		self.assertEqual((self.rst["new_bags"]["fieldtype"], self.rst["new_bags"].get("default")), ("Int", "0"))
		self.assertEqual(self.rst_order.index("new_bags"), self.rst_order.index("old_bags") + 1)

	def test_bag_condition_label_on_qc_and_grn(self):
		self.assertEqual(self.qc["old_new_bags"]["label"], "Paddy Type (In Bags)")
		self.assertEqual(self.grn["old_new_bags"]["label"], "Bag Condition (Old / New)")
		self.assertNotIn("old_bags", self.grn)


class TestRstTotal(unittest.TestCase):
	def _rst(self, **bags):
		from ivri_od.procurement.doctype.rst_details.rst_details import RSTDetails

		doc = SimpleNamespace(**bags)
		doc.get = lambda k: getattr(doc, k, 0)
		with patch("frappe.msgprint") as msgprint:
			RSTDetails._set_total_bags(doc)
		return doc.total_bags, msgprint.called

	def test_total_is_jute_plus_plastic(self):
		self.assertEqual(self._rst(jute_bags=200, plastic_bags=100, old_bags=250, new_bags=50), (300, False))

	def test_warns_when_old_plus_new_differs(self):
		self.assertEqual(self._rst(jute_bags=200, plastic_bags=100, old_bags=10, new_bags=0), (300, True))

	def test_no_warning_when_old_and_new_are_empty(self):
		self.assertEqual(self._rst(jute_bags=200, plastic_bags=0, old_bags=0, new_bags=0), (200, False))


if __name__ == "__main__":
	unittest.main()
