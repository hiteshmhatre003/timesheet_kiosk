"""
Whitelisted endpoints for the Purchase Entry mobile app.

Lives in its own app so the mobile frontend can be deployed and updated
independently of amal. Reads/writes the Purchase Entry and Item doctypes,
which live in amal - that's fine, any installed app can call frappe.get_doc
/frappe.get_all on any doctype on the same site.

Called from the React app at paths like:
  /api/method/purchase_mobile.api.search_items
  /api/method/purchase_mobile.api.create_purchase_entry
"""

import frappe
from frappe.utils import flt


EUR_WAREHOUSES = [
    "EUR Materials Rome - AE",
    "EUR Materials Paris - AE",
    "EUR Materials India - AE",
]


@frappe.whitelist()
def get_csrf_token():
    """Called once right after login so the SPA can attach
    X-Frappe-CSRF-Token on subsequent POST requests."""
    token = frappe.sessions.get_csrf_token()
    frappe.db.commit()  # nosemgrep - make sure the token is persisted before it's used
    return token


@frappe.whitelist()
def search_items(txt=""):
    """Item search box on the New Purchase screen."""
    txt = (txt or "").strip()
    filters = {"disabled": 0}
    or_filters = None
    if txt:
        or_filters = [
            ["item_code", "like", "%{0}%".format(txt)],
            ["item_name", "like", "%{0}%".format(txt)],
        ]
    return frappe.get_all(
        "Item",
        filters=filters,
        or_filters=or_filters,
        fields=["item_code", "item_name", "stock_uom"],
        order_by="item_name",
        limit=20,
    )


@frappe.whitelist()
def get_item_uoms(item_code):
    """Stock UOM plus any alternate UOMs configured on the Item, so the
    Purchase UOM dropdown offers valid choices for that specific item."""
    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    if not stock_uom:
        frappe.throw("Item {0} not found".format(item_code))

    alt = frappe.get_all(
        "UOM Conversion Detail",
        filters={"parent": item_code, "parenttype": "Item"},
        fields=["uom"],
    )
    uoms = [stock_uom] + [d.uom for d in alt if d.uom != stock_uom]
    return {"stock_uom": stock_uom, "uoms": uoms}


@frappe.whitelist()
def get_available_stock(warehouse=None):
    """Stock screen - items with positive stock across the EUR warehouses,
    with images, optionally filtered to one warehouse/region."""
    warehouses = [warehouse] if warehouse else EUR_WAREHOUSES

    bins = frappe.get_all(
        "Bin",
        filters={"warehouse": ["in", warehouses], "actual_qty": [">", 0]},
        fields=["item_code", "warehouse", "actual_qty", "stock_uom"],
        order_by="item_code",
    )
    if not bins:
        return []

    item_codes = list({b.item_code for b in bins})
    items = frappe.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "item_name", "image"],
    )
    item_map = {i.name: i for i in items}

    return [
        {
            "item_code": b.item_code,
            "item_name": item_map.get(b.item_code, {}).get("item_name"),
            "image": item_map.get(b.item_code, {}).get("image"),
            "warehouse": b.warehouse,
            "qty": flt(b.actual_qty),
            "uom": b.stock_uom,
        }
        for b in bins
    ]


@frappe.whitelist()
def create_purchase_entry(
    region=None,
    item_code=None,
    qty=None,
    uom=None,
    supplier=None,
    rate=None,
    posting_date=None,
    remarks=None,
):
    """Create + submit a Purchase Entry in one call. Expects a
    multipart/form-data POST with the fields above plus a file field
    named 'item_image'. Runs with the calling user's own permissions -
    give the mobile app role Create + Submit + Read on Purchase Entry
    only; the Purchase Entry controller's on_submit (in amal) handles
    the Stock Entry side with elevated rights internally."""

    doc = frappe.get_doc(
        {
            "doctype": "Purchase Entry",
            "region": region,
            "item_code": item_code,
            "qty": qty,
            "uom": uom,
            "supplier": supplier,
            "rate": rate or 0,
            "posting_date": posting_date,
            "remarks": remarks,
        }
    )
    doc.insert()

    image_url = _attach_image(doc, "item_image")
    if image_url:
        doc.db_set("item_image", image_url, update_modified=False)

    doc.submit()

    return {
        "name": doc.name,
        "stock_entry": doc.stock_entry,
        "item_image": doc.item_image,
    }


def _attach_image(doc, fieldname):
    file = frappe.request.files.get(fieldname) if frappe.request.files else None
    if not file:
        return None

    # Public (is_private=0) so the Stock screen can show photos to any
    # logged-in mobile-app user without needing separate Item permissions.
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file.filename,
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "attached_to_field": fieldname,
            "is_private": 0,
            "content": file.stream.read(),
        }
    )
    file_doc.insert(ignore_permissions=True)
    return file_doc.file_url
