import frappe
from frappe.model.document import Document
from frappe.utils import flt, nowdate

# Map each Region to its dedicated zero-valuation warehouse.
# Edit this if the exact Region option text differs on a given site.
REGION_WAREHOUSE_MAP = {
    "Rome": "EUR Materials Rome - AE",
    "Paris": "EUR Materials Paris - AE",
    "India": "EUR Materials India - AE",
}

RECEIPT_TYPE = "Material Receipt"  # standard ERPNext Stock Entry Type / purpose


class PurchaseEntry(Document):
    def validate(self):
        self.validate_qty()
        self.set_warehouse_from_region()

    def validate_qty(self):
        if flt(self.qty) <= 0:
            frappe.throw("Quantity must be greater than zero")

    def set_warehouse_from_region(self):
        if not self.region:
            frappe.throw("Region is mandatory")
        warehouse = REGION_WAREHOUSE_MAP.get(self.region)
        if not warehouse:
            frappe.throw(
                "No warehouse mapped for Region '{0}'. Valid regions: {1}".format(
                    self.region, ", ".join(REGION_WAREHOUSE_MAP.keys())
                )
            )
        self.warehouse = warehouse

    def on_submit(self):
        if not self.stock_entry:
            se_name = self.create_zero_value_receipt()
            self.db_set("stock_entry", se_name, update_modified=False)
        self.sync_item_image()

    def on_cancel(self):
        if self.stock_entry:
            se = frappe.get_doc("Stock Entry", self.stock_entry)
            if se.docstatus == 1:
                se.flags.ignore_permissions = True
                se.cancel()

    def create_zero_value_receipt(self):
        company = frappe.db.get_value("Warehouse", self.warehouse, "company")
        if not company:
            frappe.throw(
                "Warehouse {0} is not linked to a Company".format(self.warehouse)
            )

        stock_uom, conversion_factor = self.get_uom_and_factor()

        se = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": RECEIPT_TYPE,
                "purpose": RECEIPT_TYPE,
                "company": company,
                "posting_date": self.posting_date or nowdate(),
                "set_posting_time": 1,
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": flt(self.qty),
                        "uom": self.uom,
                        "stock_uom": stock_uom,
                        "conversion_factor": conversion_factor,
                        "transfer_qty": flt(self.qty) * conversion_factor,
                        "t_warehouse": self.warehouse,
                        "basic_rate": 0,
                        "allow_zero_valuation_rate": 1,
                    }
                ],
            }
        )
        se.flags.ignore_permissions = True
        se.insert()
        se.submit()
        return se.name

    def get_uom_and_factor(self):
        stock_uom = frappe.db.get_value("Item", self.item_code, "stock_uom")
        if not stock_uom:
            frappe.throw("Item {0} has no Stock UOM set".format(self.item_code))

        if self.uom == stock_uom:
            return stock_uom, 1.0

        factor = frappe.db.get_value(
            "UOM Conversion Detail",
            {"parent": self.item_code, "parenttype": "Item", "uom": self.uom},
            "conversion_factor",
        )
        return stock_uom, flt(factor) or 1.0

    def sync_item_image(self):
        if self.item_image:
            frappe.db.set_value("Item", self.item_code, "image", self.item_image)
