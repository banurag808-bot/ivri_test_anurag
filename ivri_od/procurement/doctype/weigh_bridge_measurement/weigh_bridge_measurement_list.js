// Copyright (c) 2026, Profezzo and contributors
// For license information, please see license.txt

// List view settings must live in this *_list.js file: Frappe loads the form script only after a form
// of this DocType has been opened, so settings kept there are missing after a page refresh.

// Pass Unique Key is {miller}-{PPC NAME(CODE)}-{K|R}{YY}-TP{no}; the PPC part is the last-resort party name.
function ppcFromPassKey(key) {
	const match = /^[^-]+-(.+?)-[A-Z]\d{2}-TP/i.exec(key || "");
	return match ? match[1] : "";
}

// Quality Test has three statuses: "Pending QC" (no Quality Check found), "Accepted" and
// "Partially Accepted" (both come from the Quality Check result).
const WBM_QC_STATUSES = ["Pending QC", "Accepted", "Partially Accepted"];

function wbm_quality_status(value, doc) {
	const status = (value || "").trim();
	if (!(doc && (doc.quality_check || "").trim()) && status !== "Pending QC") return "Pending QC";
	return WBM_QC_STATUSES.includes(status) ? status : "Pending QC";
}

// The list shows only these columns, in this order (RST No is the title field, so it is always first).
const WBM_LIST_COLUMN_ORDER = [
	"rst_no",
	"transaction_type",
	"actual_truck_no",
	"truck_no_in_tp",
	"transit_pass_no",
	"lot_no",
	"party_name",
	"commodity",
	"load_weight",
	"tare_weight",
	"gross_weight",
	"gunny_weight",
	"deduction",
	"net_weight",
	"tp_status",
	"quality_test",
	"date",
];

// Short list headings. Display only: the form labels stay the same.
const WBM_LIST_LABELS = {
	transit_pass_no: "TP No",
	actual_truck_no: "Arrived Vehicle No",
	truck_no_in_tp: "TP Vehicle No",
	load_weight: "Load Wt",
	tare_weight: "Tare Wt",
	gross_weight: "Gross Wt",
	gunny_weight: "Gunny Wt",
	deduction: "Dust",
	net_weight: "Net Wt",
	date: "Date",
};

// Widths in pixels, wide enough for the heading and a normal value. Staff can still drag a column edge.
const WBM_LIST_WIDTHS = {
	rst_no: 120,
	transaction_type: 140,
	party_name: 220,
	transit_pass_no: 110,
	lot_no: 120,
	actual_truck_no: 170,
	truck_no_in_tp: 150,
	commodity: 130,
	load_weight: 100,
	tare_weight: 100,
	gross_weight: 100,
	gunny_weight: 100,
	deduction: 90,
	net_weight: 100,
	tp_status: 150,
	quality_test: 160,
	date: 120,
};

function wbm_list_column(fieldname, existing) {
	const df = (existing && existing.df) || frappe.meta.get_docfield("Weigh Bridge Measurement", fieldname);
	if (!df) {
		return null;
	}

	// Copy the field so the heading, width and "not hidden" apply only in the list.
	return Object.assign({}, df, {
		hidden: 0,
		label: WBM_LIST_LABELS[fieldname] || df.label,
		width: WBM_LIST_WIDTHS[fieldname] || df.width,
	});
}

function setup_wbm_list_columns(listview) {
	const columns = listview.columns || [];
	const signature = columns.map((col) => (col.df && col.df.fieldname) || col.type).join("|");

	const existing = {};
	columns
		.filter((col) => (col.type === "Field" || col.type === "Subject") && col.df)
		.forEach((col) => {
			existing[col.df.fieldname] = col;
		});

	const ordered = [];
	for (const col of columns) {
		if (col.type === "Subject") {
			const df = wbm_list_column(col.df.fieldname, col);
			ordered.push(df ? Object.assign({}, col, { df }) : col);
		} else if (col.type === "Tag" || col.type === "Status") {
			ordered.push(col);
		}
	}
	for (const fieldname of WBM_LIST_COLUMN_ORDER) {
		if (ordered.some((col) => col.df && col.df.fieldname === fieldname)) {
			continue;
		}
		const df = wbm_list_column(fieldname, existing[fieldname]);
		if (df) {
			ordered.push({ type: "Field", df });
		}
	}

	listview.columns = ordered;
	return signature !== ordered.map((col) => (col.df && col.df.fieldname) || col.type).join("|");
}

frappe.listview_settings["Weigh Bridge Measurement"] = {
	// The ID column (WBM-2026-00071) is not useful: RST No is the clickable first column.
	hide_name_column: true,
	// Party Name is copied from the RST on every RST save. Older records without it show their
	// PPC Name, else the PPC from the Pass Unique Key. Display only: nothing is saved.
	add_fields: ["pacs_name", "pass_unique_key", "quality_check"],
	formatters: {
		// Show the date only. Display only: the time is still saved and shown on the form.
		date(value) {
			if (!value) {
				return "";
			}
			const date = frappe.utils.escape_html(frappe.datetime.str_to_user(String(value).split(/[ T]/)[0]));
			return `<span class="ellipsis" title="${date}">${date}</span>`;
		},
		quality_test(value, df, doc) {
			const raw = wbm_quality_status(value, doc);
			const status = frappe.utils.escape_html(__(raw));
			const color = { Accepted: "green", "Partially Accepted": "blue" }[raw] || "orange";
			return `<span class="indicator-pill ${color} ellipsis" title="${status}"><span class="ellipsis">${status}</span></span>`;
		},
		party_name(value, df, doc) {
			const party = frappe.utils.escape_html(
				value || doc.pacs_name || ppcFromPassKey(doc.pass_unique_key)
			);
			return `<span class="ellipsis" title="${__("Party Name")}: ${party}">${party}</span>`;
		},
	},
	// No ID filter: RST No, Party Name, TP No, Lot No, Truck No and Commodity are the filters staff use.
	// Each one is a drop-down of the values that exist in the weighments.
	hide_name_filter: true,
	onload(listview) {
		// A saved column layout keeps only the columns named in it, and Frappe rebuilds the columns when
		// that layout loads. So re-apply our columns after every rebuild.
		const frappe_setup_columns = listview.setup_columns.bind(listview);
		listview.setup_columns = async function (...args) {
			await frappe_setup_columns(...args);
			setup_wbm_list_columns(listview);
		};
		if (setup_wbm_list_columns(listview)) {
			listview.refresh(true);
		}

		// Open with no filter: Frappe remembers the filters used last time, which hid data from staff.
		// A link with filters in its address (route options) is left alone.
		if (!Object.keys(frappe.route_options || {}).length && listview.filter_area) {
			listview.filter_area.clear();
		}
		make_wbm_filters_dropdown(listview);
	},
};

// The filters above the list, in this order. Each one is a dropdown: the two Select fields keep
// their fixed choices, the others list the values already saved in the weighments.
const WBM_FILTERS = [
	"rst_no",
	"actual_truck_no",
	"truck_no_in_tp",
	"transit_pass_no",
	"lot_no",
	"party_name",
	"commodity",
	"transaction_type",
	"tp_status",
	"quality_test",
];
const WBM_FILTER_LABELS = {
	actual_truck_no: "Arrived Vehicle No",
	truck_no_in_tp: "TP Vehicle No",
};

// Status drop-down. Status has too many saved values to list one by one (every commodity of a private
// deal has its own "Local {Commodity} {Purchase|Sale}" text), so the private deals are grouped.
const WBM_STATUS_FILTERS = {
	"TP Received": ["=", "TP Received"],
	"TP Not Received": ["=", "TP Not Received"],
	"PPC Mismatch": ["=", "PPC Mismatch"],
	"Rice Dispatch": ["=", "Rice Dispatch"],
	"Local (Private) - All": ["like", "Local%"],
	"Local - Purchase": ["like", "Local% Purchase"],
	"Local - Sale": ["like", "Local% Sale"],
};

function add_wbm_status_filter(listview, wrapper) {
	if (listview.wbm_status_filter) {
		$(listview.wbm_status_filter.wrapper).remove();
	}
	listview.wbm_status_filter = listview.page.add_field(
		{
			fieldname: "wbm_status_filter",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", ...Object.keys(WBM_STATUS_FILTERS)].map((label) => ({ label: __(label), value: label })),
			change() {
				const chosen = WBM_STATUS_FILTERS[this.get_value()];
				const area = listview.filter_area;
				// Drop the previous Status choice, then apply the new one.
				area.filter_list.get_filter("tp_status")?.remove();
				if (chosen) {
					area.add([["Weigh Bridge Measurement", "tp_status", ...chosen]]);
				} else {
					area.filter_list.apply();
				}
			},
		},
		wrapper
	);
	// Frappe sends every field in page.fields_dict to the query as "fieldname = value". This drop-down is not
	// a column (it applies the tp_status filter above), so keep it out of that list.
	delete listview.page.fields_dict.wbm_status_filter;
}

async function make_wbm_filters_dropdown(listview) {
	const wrapper = listview.filter_area && listview.filter_area.standard_filters_wrapper;
	if (!wrapper) return;

	const values = await frappe.xcall(
		"ivri_od.procurement.doctype.weigh_bridge_measurement.weigh_bridge_measurement.get_filter_values"
	);
	// The filter boxes are made a moment after the list opens: wait for all of them.
	for (let tries = 0; tries < 40 && !WBM_FILTERS.every((n) => listview.page.fields_dict[n]); tries++) {
		await new Promise((resolve) => setTimeout(resolve, 250));
	}

	WBM_FILTERS.forEach((fieldname) => {
		const old_field = listview.page.fields_dict[fieldname];
		if (!old_field) return;
		$(old_field.wrapper).remove();
		delete listview.page.fields_dict[fieldname];
	});

	WBM_FILTERS.forEach((fieldname) => {
		if (fieldname === "tp_status") {
			add_wbm_status_filter(listview, wrapper);
			return;
		}
		const meta = frappe.meta.get_docfield("Weigh Bridge Measurement", fieldname);
		if (!meta) return;
		const is_select = meta.fieldtype === "Select";
		let options = is_select ? ["", ...(meta.options || "").split("\n").filter(Boolean)].join("\n") : values[fieldname] || [];
		listview.page.add_field(
			{
				fieldtype: is_select ? "Select" : "Autocomplete",
				fieldname: fieldname,
				label: WBM_FILTER_LABELS[fieldname] || meta.label,
				options: options,
				condition: "=",
				is_filter: 1,
				onchange: () => listview.filter_area.debounced_refresh_list_view(),
			},
			wrapper
		);
	});

	// Date: a from-to range. "date" holds the date and time, so an exact match would hardly ever hit;
	// "Between" takes every weighment from the start of the first day to the end of the last day.
	if (!listview.page.fields_dict.date) {
		listview.page.add_field(
			{
				fieldtype: "DateRange",
				fieldname: "date",
				label: __("Date"),
				condition: "Between",
				is_filter: 1,
				onchange: () => listview.filter_area.debounced_refresh_list_view(),
			},
			wrapper
		);
	}
}

// The list columns that are not "In List View" in the DocType must be fetched too.
WBM_LIST_COLUMN_ORDER.forEach((fieldname) => {
	const settings = frappe.listview_settings["Weigh Bridge Measurement"];
	if (!settings.add_fields.includes(fieldname)) {
		settings.add_fields.push(fieldname);
	}
});
