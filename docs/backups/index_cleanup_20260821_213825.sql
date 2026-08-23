-- 索引清理备份（可回滚）
-- 时间: 2026-08-21 21:38:25

-- case.ix_case_barcode
CREATE INDEX ix_case_barcode ON public."case" USING btree (barcode);

-- case.ix_case_product_id
CREATE INDEX ix_case_product_id ON public."case" USING btree (product_id);

-- customer_sampling_project.idx_csp_sequence_no
CREATE INDEX idx_csp_sequence_no ON public.customer_sampling_project USING btree (sequence_no);

-- inventory_log.idx_inventory_log_product_date
CREATE INDEX idx_inventory_log_product_date ON public.inventory_log USING btree (product_id, change_date DESC);

-- material_registration_item.idx_material_reg_item_reg_id
CREATE INDEX idx_material_reg_item_reg_id ON public.material_registration_item USING btree (registration_id);

-- modification_log.ix_modification_log_modify_time
CREATE INDEX ix_modification_log_modify_time ON public.modification_log USING btree (modify_time);

-- order_batch_audit_log.ix_order_batch_audit_log_created_at
CREATE INDEX ix_order_batch_audit_log_created_at ON public.order_batch_audit_log USING btree (created_at);

-- order_status_log.ix_order_status_log_action_time
CREATE INDEX ix_order_status_log_action_time ON public.order_status_log USING btree (action_time);

-- order_sync_record.ix_order_sync_record_source_order_id
CREATE INDEX ix_order_sync_record_source_order_id ON public.order_sync_record USING btree (source_order_id);

-- product_material.idx_product_material_product
CREATE INDEX idx_product_material_product ON public.product_material USING btree (product_id);

-- production_plan.ix_production_plan_barcode
CREATE INDEX ix_production_plan_barcode ON public.production_plan USING btree (barcode);

-- production_plan.ix_production_plan_customer_name
CREATE INDEX ix_production_plan_customer_name ON public.production_plan USING btree (customer_name);

-- saved_query.ix_saved_query_query_type
CREATE INDEX ix_saved_query_query_type ON public.saved_query USING btree (query_type);

-- staging_order.ix_staging_order_session_id
CREATE INDEX ix_staging_order_session_id ON public.staging_order USING btree (session_id);

-- staging_purchase_plan.ix_staging_purchase_plan_session_id
CREATE INDEX ix_staging_purchase_plan_session_id ON public.staging_purchase_plan USING btree (session_id);

-- staging_purchase_plan.ix_staging_purchase_plan_upload_batch_id
CREATE INDEX ix_staging_purchase_plan_upload_batch_id ON public.staging_purchase_plan USING btree (upload_batch_id);

-- staging_stock_in.ix_staging_stock_in_session_id
CREATE INDEX ix_staging_stock_in_session_id ON public.staging_stock_in USING btree (session_id);

-- staging_stock_out.ix_staging_stock_out_session_id
CREATE INDEX ix_staging_stock_out_session_id ON public.staging_stock_out USING btree (session_id);

-- supplier.idx_supplier_name
CREATE INDEX idx_supplier_name ON public.supplier USING btree (name);
