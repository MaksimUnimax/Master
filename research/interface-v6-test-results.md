# Итоговые журналы accounting-v6

Независимые UI: 13/14 полностью, один сценарий авторизации частично. Итоговый прогон 13 независимых сценариев и прежнего сквозного: 14/14. Серверный учёт: 40/40. Авторизация после 60-секундного ограничения не перепроверена; механизмы авторизации не изменены.

## Браузерный прогон

```text
test_01_public_navigation_cookie_choices (test_podmasterye_independent_ui.IndependentUI.test_01_public_navigation_cookie_choices) ... ok
test_02_calculator_validation_live_recalculation (test_podmasterye_independent_ui.IndependentUI.test_02_calculator_validation_live_recalculation) ... ok
test_03_calculator_guest_to_account_save (test_podmasterye_independent_ui.IndependentUI.test_03_calculator_guest_to_account_save) ... ok
test_05_all_tabs_empty_and_responsive (test_podmasterye_independent_ui.IndependentUI.test_05_all_tabs_empty_and_responsive) ... ok
test_06_themes_colors_and_workshop_restore (test_podmasterye_independent_ui.IndependentUI.test_06_themes_colors_and_workshop_restore) ... ok
test_07_category_sales_purchase_filters (test_podmasterye_independent_ui.IndependentUI.test_07_category_sales_purchase_filters) ... ok
test_08_catalog_views_and_material_autofill (test_podmasterye_independent_ui.IndependentUI.test_08_catalog_views_and_material_autofill) ... ok
test_09_product_card_photo_edit_and_archive (test_podmasterye_independent_ui.IndependentUI.test_09_product_card_photo_edit_and_archive) ... ok
test_10_finance_charts_distribution_rank_and_periods (test_podmasterye_independent_ui.IndependentUI.test_10_finance_charts_distribution_rank_and_periods) ... ok
test_11_task_filters_all_categories_reminders (test_podmasterye_independent_ui.IndependentUI.test_11_task_filters_all_categories_reminders) ... ok
test_12_local_integration_clipboard_rotation_and_mapping (test_podmasterye_independent_ui.IndependentUI.test_12_local_integration_clipboard_rotation_and_mapping) ... ok
test_13_exports_and_template_downloads (test_podmasterye_independent_ui.IndependentUI.test_13_exports_and_template_downloads) ... ok
test_14_assistant_highlight_and_navigation (test_podmasterye_independent_ui.IndependentUI.test_14_assistant_highlight_and_navigation) ... ok
test_accounting_workflow (test_podmasterye_accounting_browser.AccountingBrowser.test_accounting_workflow) ... ok

----------------------------------------------------------------------
Ran 14 tests in 107.438s

OK
```

## Серверный прогон

```text
test_atomic_preview_and_stale_revision (tests.test_podmasterye_accounting.Accounting.test_atomic_preview_and_stale_revision) ... ok
test_catalog_and_units (tests.test_podmasterye_accounting.Accounting.test_catalog_and_units) ... ok
test_date_period_and_no_backdated_stock (tests.test_podmasterye_accounting.Accounting.test_date_period_and_no_backdated_stock) ... ok
test_every_matrix_entry_has_zero_model_route (tests.test_podmasterye_accounting.Accounting.test_every_matrix_entry_has_zero_model_route) ... ok
test_exact_kopeck_conservation (tests.test_podmasterye_accounting.Accounting.test_exact_kopeck_conservation) ... ok
test_exports (tests.test_podmasterye_accounting.Accounting.test_exports) ... ok
test_external_order_mapping_retry_returns_and_key_rotation (tests.test_podmasterye_accounting.Accounting.test_external_order_mapping_retry_returns_and_key_rotation) ... ok
test_idempotent_commit_and_conflict (tests.test_podmasterye_accounting.Accounting.test_idempotent_commit_and_conflict) ... ok
test_import_csv_and_xlsx_atomic_and_idempotent (tests.test_podmasterye_accounting.Accounting.test_import_csv_and_xlsx_atomic_and_idempotent) ... ok
test_invalid_values_no_mutation (tests.test_podmasterye_accounting.Accounting.test_invalid_values_no_mutation) ... ok
test_matrix_draft_does_not_write_and_reads_report (tests.test_podmasterye_accounting.Accounting.test_matrix_draft_does_not_write_and_reads_report) ... ok
test_moving_average_and_fifo_control (tests.test_podmasterye_accounting.Accounting.test_moving_average_and_fifo_control) ... ok
test_multi_material_failure_is_atomic (tests.test_podmasterye_accounting.Accounting.test_multi_material_failure_is_atomic) ... ok
test_multiple_workshops_and_demo_isolation (tests.test_podmasterye_accounting.Accounting.test_multiple_workshops_and_demo_isolation) ... ok
test_no_double_consumption_and_stock_bound (tests.test_podmasterye_accounting.Accounting.test_no_double_consumption_and_stock_bound) ... ok
test_other_workspace_cannot_read_or_commit (tests.test_podmasterye_accounting.Accounting.test_other_workspace_cannot_read_or_commit) ... ok
test_pack_purchase_and_forecast (tests.test_podmasterye_accounting.Accounting.test_pack_purchase_and_forecast) ... ok
test_payment_and_return_good_and_damaged (tests.test_podmasterye_accounting.Accounting.test_payment_and_return_good_and_damaged) ... ok
test_public_calculator_and_save (tests.test_podmasterye_accounting.Accounting.test_public_calculator_and_save) ... ok
test_recipe_versions_archive_and_restore (tests.test_podmasterye_accounting.Accounting.test_recipe_versions_archive_and_restore) ... ok
test_reversal_preserves_audit_and_dependency (tests.test_podmasterye_accounting.Accounting.test_reversal_preserves_audit_and_dependency) ... ok
test_specific_material_reports_and_rename (tests.test_podmasterye_accounting.Accounting.test_specific_material_reports_and_rename) ... ok
test_tasks_create_edit_complete_archive (tests.test_podmasterye_accounting.Accounting.test_tasks_create_edit_complete_archive) ... ok
test_unit_economics_labor_and_channel_tariff (tests.test_podmasterye_accounting.Accounting.test_unit_economics_labor_and_channel_tariff) ... ok
test_unpaid_sale_and_partial_payment (tests.test_podmasterye_accounting.Accounting.test_unpaid_sale_and_partial_payment) ... ok
test_v5_actual_fees_and_distribution (tests.test_podmasterye_accounting.Accounting.test_v5_actual_fees_and_distribution) ... ok
test_v5_all_expense_categories_and_report_reconciliation (tests.test_podmasterye_accounting.Accounting.test_v5_all_expense_categories_and_report_reconciliation) ... ok
test_v5_calculator_margins (tests.test_podmasterye_accounting.Accounting.test_v5_calculator_margins) ... ok
test_v5_depreciation_acquisition_and_disposal (tests.test_podmasterye_accounting.Accounting.test_v5_depreciation_acquisition_and_disposal) ... ok
test_v5_edit_and_delete_sale_and_manufacture (tests.test_podmasterye_accounting.Accounting.test_v5_edit_and_delete_sale_and_manufacture) ... ok
test_v5_external_catalog_fixture (tests.test_podmasterye_accounting.Accounting.test_v5_external_catalog_fixture) ... ok
test_v5_historical_insert_delete_and_rollback (tests.test_podmasterye_accounting.Accounting.test_v5_historical_insert_delete_and_rollback) ... ok
test_v5_historical_purchase_frozen_recipe (tests.test_podmasterye_accounting.Accounting.test_v5_historical_purchase_frozen_recipe) ... ok
test_v5_manual_cost_and_returns (tests.test_podmasterye_accounting.Accounting.test_v5_manual_cost_and_returns) ... ok
test_v5_opening_and_full_writeoff (tests.test_podmasterye_accounting.Accounting.test_v5_opening_and_full_writeoff) ... ok
test_v5_overheads_and_target_price (tests.test_podmasterye_accounting.Accounting.test_v5_overheads_and_target_price) ... ok
test_v5_photos_and_bulk_archive (tests.test_podmasterye_accounting.Accounting.test_v5_photos_and_bulk_archive) ... ok
test_v5_reminders_and_full_export (tests.test_podmasterye_accounting.Accounting.test_v5_reminders_and_full_export) ... ok
test_v5_wip_and_component_cost (tests.test_podmasterye_accounting.Accounting.test_v5_wip_and_component_cost) ... ok
test_worker_payments_and_reversal (tests.test_podmasterye_accounting.Accounting.test_worker_payments_and_reversal) ... ok

----------------------------------------------------------------------
Ran 40 tests in 142.301s

OK
```
