// Copyright (c) 2026, Profezzo and contributors
// For license information, please see license.txt

// List view settings must live in this *_list.js file: Frappe loads the form script only after a form
// of this DocType has been opened, so settings kept there are missing after a page refresh.

// Mill Name holds "SHREE SHYAMJI PADDY PROCESSING PVT LTD(M051007)". The list shows the mill's Short Name
// from Mill Master (SSPPB), which is much shorter. Display only: nothing is saved.
const GRN_MILL_SHORT_NAMES = {};

function load_grn_mill_short_names() {
	return frappe.db.get_list("Mill Master", { fields: ["name", "short_name"], limit: 100 }).then((rows) => {
		(rows || []).forEach((row) => {
			if (row.short_name) GRN_MILL_SHORT_NAMES[row.name] = row.short_name;
		});
	});
}

// One GRN form for every weighment. GRN Type tells them apart; the buttons on top of the list filter on it.
const GRN_TYPE_BUTTONS = [
	{ label: "All", value: "" },
	{ label: "Government", value: "Government Paddy" },
	{ label: "Rice", value: "Rice Delivery to Depo" },
	{ label: "Private", value: "Private Deal" },
];
const GRN_TYPE_COLORS = { "Government Paddy": "blue", "Rice Delivery to Depo": "orange", "Private Deal": "purple" };

// List columns, in this order. GRN No is the first column (title field). Frappe orders columns by the form's
// field order, so the order is set here and the form layout is left alone. A user's own saved layout still wins.
const GRN_LIST_COLUMNS = [
	"grn_no", "grn_type", "mill_name", "ppc", "vehicle_no", "commodity", "transit_pass_no", "lot_no",
	"no_of_bags", "gross_vehicle_weight", "tare_weight", "gross_weight", "gunny_weight", "deduction",
	"net_weight", "moisture", "dust", "receipt_date",
];
// Short headings for the list only (the form keeps its own labels).
const GRN_LIST_LABELS = { mill_name: "Mill", receipt_date: "Date" };

function apply_grn_list_columns(listview) {
	if (listview.grn_columns_applied) {
		return Promise.resolve();
	}
	listview.grn_columns_applied = true;
	const setup_columns = listview.setup_columns.bind(listview);
	listview.setup_columns = async function (fields_override = null) {
		const layout = listview.list_filter && listview.list_filter.active_layout_name;
		const custom_layout = layout && layout !== "default_layout";
		const use_default = !custom_layout && !(fields_override && fields_override.length);
		await setup_columns(use_default ? GRN_LIST_COLUMNS.map((fieldname) => ({ fieldname })) : fields_override);
		listview.columns.forEach((col) => {
			const label = col.df && GRN_LIST_LABELS[col.df.fieldname];
			if (label) col.df.label = __(label);
		});
	};
	return listview.setup_columns();
}

// Filters above the list, in this order. GRN No is the title field, so Frappe adds it by itself.
const GRN_FILTERS = [
	"grn_no", "grn_type", "mill_name", "ppc", "vehicle_no", "commodity", "transit_pass_no", "lot_no",
	"no_of_bags", "moisture", "dust", "receipt_date",
];
const GRN_FILTER_LABELS = { mill_name: "Mill", receipt_date: "Date" };

// These filters are pick-lists of the values already saved in GRN Notes (you can still type to search).
// Frappe builds them from here, not from the form field flags. Moisture and Dust stay typed boxes.
const GRN_DROPDOWN_FILTERS = [
	["mill_name", "Mill"], ["ppc", "PPC"], ["vehicle_no", "Vehicle"], ["commodity", "Commodity"],
	["transit_pass_no", "TP No"], ["lot_no", "Lot No"],
];

function grn_dropdown_filter_configs() {
	return Promise.all(
		GRN_DROPDOWN_FILTERS.map(([fieldname, label]) =>
			frappe.db
				.get_list("GRN Note", {
					fields: [fieldname],
					filters: [[fieldname, "is", "set"]],
					group_by: fieldname,
					order_by: `${fieldname} asc`,
					limit: 1000,
				})
				.catch(() => [])
				.then((rows) => ({
					fieldtype: "Autocomplete",
					fieldname,
					label: __(label),
					condition: "=",
					is_filter: 1,
					options: (rows || []).map((r) => r[fieldname]).filter(Boolean),
				}))
		)
	);
}

// Frappe builds the filters in form-field order and a moment after onload, so wait for them, then reorder.
function arrange_grn_filters(listview, tries = 0) {
	const fields = listview.page.fields_dict || {};
	if (!GRN_FILTERS.every((name) => fields[name])) {
		if (tries < 50) setTimeout(() => arrange_grn_filters(listview, tries + 1), 100);
		return;
	}
	const $section = $(fields[GRN_FILTERS[0]].wrapper).parent();
	GRN_FILTERS.forEach((name) => {
		const field = fields[name];
		$section.append(field.wrapper);
		const label = GRN_FILTER_LABELS[name];
		if (label && field.$input) {
			field.$input.attr("placeholder", __(label));
			$(field.wrapper).attr("title", __(label)).attr("data-original-title", __(label));
		}
	});
}

function add_grn_type_buttons(listview) {
	if (!listview.page || listview.grn_type_buttons) {
		return;
	}
	const $group = $('<div class="btn-group grn-type-buttons" role="group" style="margin-right:8px;"></div>');
	const mark = () => {
		const current = (listview.filter_area.get().find((f) => f[1] === "grn_type") || [])[3] || "";
		$group.find("button").each(function () {
			const active = $(this).attr("data-value") === current;
			$(this).toggleClass("btn-primary", active).toggleClass("btn-default", !active);
		});
	};
	GRN_TYPE_BUTTONS.forEach(({ label, value }) => {
		$(`<button type="button" class="btn btn-default btn-sm" data-value="${value}"></button>`)
			.text(__(label))
			.on("click", () => {
				const area = listview.filter_area;
				const done = value ? area.remove("grn_type").then(() => area.add([["GRN Note", "grn_type", "=", value]])) : area.remove("grn_type");
				Promise.resolve(done).then(mark);
			})
			.appendTo($group);
	});
	listview.page.page_actions.prepend($group);
	listview.grn_type_buttons = $group;
	mark();
}

frappe.listview_settings["GRN Note"] = {
	// GRN No is the first column; the ID column and the ID filter repeat it.
	hide_name_column: true,
	hide_name_filter: true,
	custom_filter_configs: grn_dropdown_filter_configs,
	add_fields: ["grn_type"],
	get_indicator(doc) {
		const type = doc.grn_type || "Government Paddy";
		return [__(type), GRN_TYPE_COLORS[type] || "gray", `grn_type,=,${type}`];
	},
	onload(listview) {
		apply_grn_list_columns(listview).then(() => listview.refresh(true));
		load_grn_mill_short_names().then(() => listview.refresh());
		add_grn_type_buttons(listview);
		arrange_grn_filters(listview);
	},
	formatters: {
		mill_name(value) {
			const text = value || "";
			const code = (/\(([^)]+)\)\s*$/.exec(text) || [])[1] || text;
			const short = GRN_MILL_SHORT_NAMES[code.trim()] || text;
			return `<span class="ellipsis" title="${frappe.utils.escape_html(text)}">${frappe.utils.escape_html(short)}</span>`;
		},
	},
};
