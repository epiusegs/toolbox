# Copyright (c) 2023, Gavin D'souza and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from toolbox.utils import check_dbms_compatibility

PROCESS_SQL_JOB_TITLE = "Process SQL Recorder"
PROCESS_SQL_JOB_METHOD = "toolbox_settings.process_sql_recorder"


class ToolBoxSettings(Document):
    def validate(self):
        with check_dbms_compatibility(frappe.conf, raise_error=True):
            ...
        self.set_missing_settings()
        self.update_scheduled_job()

    def on_change(self):
        # clear bootinfo for all System Managers
        for user in frappe.get_all(
            "Has Role", filters={"role": "System Manager"}, pluck="parent", distinct=True
        ):
            frappe.cache().hdel("bootinfo", user)

    def set_missing_settings(self):
        if self.is_index_manager_enabled:
            self.is_sql_recorder_enabled = True
        if not self.sql_recorder_processing_interval:
            self.sql_recorder_processing_interval = "Hourly"

    def update_scheduled_job(self):
        if not frappe.db.exists("Scheduled Job Type", "toolbox_settings.process_sql_recorder"):
            scheduled_job = frappe.new_doc("Scheduled Job Type")
            scheduled_job.name = PROCESS_SQL_JOB_METHOD
        else:
            scheduled_job = frappe.get_doc("Scheduled Job Type", PROCESS_SQL_JOB_METHOD)

        scheduled_job.stopped = not self.is_sql_recorder_enabled
        scheduled_job.method = (
            "toolbox.toolbox.doctype.toolbox_settings.toolbox_settings.process_sql_recorder"
        )
        scheduled_job.create_log = 1

        if "*" in self.sql_recorder_processing_interval:
            scheduled_job.frequency = "Cron"
            scheduled_job.cron_format = self.sql_recorder_processing_interval
        else:
            scheduled_job.frequency = self.sql_recorder_processing_interval + " Long"

        scheduled_job.save()


def process_sql_recorder():
    import frappe
    from frappe.utils.synchronization import filelock

    from toolbox.sql_recorder import TOOLBOX_RECORDER_FLAG, delete_data, export_data
    from toolbox.utils import _process_sql_metadata_chunk, record_database_state

    CHUNK_SIZE = 2500

    with filelock("process_sql_metadata", timeout=0.1):
        # stop recording queries while processing
        frappe.cache().delete_value(TOOLBOX_RECORDER_FLAG)
        KEEP_RECORDER_ON = frappe.conf.toolbox and frappe.conf.toolbox.get("recorder")
        queries = [query for request_data in export_data() for query in request_data]

        print(f"Processing {len(queries):,} queries")
        record_database_state(init=True)
        _process_sql_metadata_chunk(queries, chunk_size=CHUNK_SIZE, show_progress=False)
        frappe.enqueue(
            record_database_state,
            queue="long",
        )
        print("Done processing queries across all jobs")

        delete_data()

        if KEEP_RECORDER_ON:
            frappe.cache().set_value(TOOLBOX_RECORDER_FLAG, 1)
        else:
            print("*** SQL Recorder switched off ***")