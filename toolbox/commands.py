# bench --site business.localhost start-recording
# bench --site business.localhost execute frappe.recorder.export_data
# changed `save 30 100` in redis_cache from `save ""` to persist data

import click
from frappe.commands import get_site, pass_context


@click.command("delete-recording")
@pass_context
def delete_recording(context):
    import frappe
    from frappe.recorder import delete

    with frappe.init_site(get_site(context)):
        frappe.connect()
        delete()


@click.command("process-sql-metadata")
@pass_context
def process_sql_metadata(context):
    import frappe
    from frappe.recorder import export_data

    from toolbox.utils import (
        check_dbms_compatibility,
        handle_redis_connection_error,
        record_database_state,
        record_query,
    )

    with frappe.init_site(get_site(context)), check_dbms_compatibility(
        frappe.conf
    ), handle_redis_connection_error():
        frappe.connect()

        sql_count = 0
        TOOLBOX_TABLES = frappe.get_all("DocType", {"module": "Toolbox"}, pluck="name")

        record_database_state()
        exported_data = export_data()

        for func_call in exported_data:
            for query_info in func_call["calls"]:
                query = query_info["query"]

                if query.lower().startswith(("start", "commit", "rollback")):
                    continue

                if explain_data := query_info["explain_result"]:
                    query_record = record_query(query)

                    for explain in explain_data:
                        # skip Toolbox internal queries
                        if explain["table"] in TOOLBOX_TABLES:
                            continue

                        query_record.apply_explain(explain)

                    query_record.save()
                    sql_count += 1

                else:
                    if not query.lower().startswith("insert"):
                        print(f"Skipping query: {query}")
                    continue

            print(f"Write Transactions: {frappe.db.transaction_writes}", end="\r")

        print(f"Processed {sql_count} queries" + " " * 5)
        frappe.db.commit()
        delete_recording.callback()


@click.command("cleanup-sql-metadata")
@pass_context
def cleanup_sql_metadata(context):
    from collections import Counter

    import frappe

    with frappe.init_site(get_site(context)):
        frappe.connect()
        mdb_qry = frappe.qb.DocType("MariaDB Query")
        candidates = frappe.get_all("MariaDB Query", pluck="query")
        c = Counter()
        c.update(candidates)

        candidates = [q for q, count in c.most_common(10_000) if count > 1]

        for query in candidates:
            all_occurences = frappe.get_all("MariaDB Query", {"query": query}, pluck="name")
            pick = all_occurences[0]
            frappe.qb.from_(mdb_qry).where(mdb_qry.query == query).where(
                mdb_qry.name != pick
            ).delete().run()
            doc = frappe.get_doc("MariaDB Query", pick)
            doc.occurence = len(all_occurences)
            doc.save()
            frappe.db.commit()


commands = [process_sql_metadata, delete_recording, cleanup_sql_metadata]