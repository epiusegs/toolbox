# Copyright (c) 2023, Gavin D'souza and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint

from toolbox.utils import record_table


class MariaDBQuery(Document):
    def validate(self):
        self.set_tables_summary()

    def set_tables_summary(self):
        seen = set()
        tables_id = [
            x.table for x in self.query_explain if not (x.table in seen or seen.add(x.table))
        ]
        tables = frappe.get_all(
            "MariaDB Table", filters={"name": ("in", tables_id)}, fields=["name", "_table_name"]
        )
        tables.sort(key=lambda x: tables_id.index(x["name"]))
        self.tables = frappe.as_json([x._table_name for x in tables], indent=0)

    def apply_explain(self, explain: dict):
        table_id = record_table(explain["table"])

        explain_row = {
            "id": explain["id"],
            "select_type": explain["select_type"],
            "table": table_id,
            "type": explain["type"],
            "possible_keys": explain["possible_keys"],
            "key": explain["key"],
            "key_len": cint(explain["key_len"]),
            "ref": explain["ref"],
            "extra": explain["Extra"],
        }

        if self.get("query_explain", explain_row):
            return

        self.append(
            "query_explain",
            explain_row | {"rows": cint(explain["rows"]), "filtered": explain.get("filtered")},
        )