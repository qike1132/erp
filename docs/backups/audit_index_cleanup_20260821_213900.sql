-- audit_log 未使用索引清理备份（可回滚）
-- 时间: 2026-08-21 21:39:00

-- audit_log.idx_audit_resource_date
CREATE INDEX idx_audit_resource_date ON public.audit_log USING btree (resource_type, created_at DESC);

-- audit_log.idx_audit_created_desc
CREATE INDEX idx_audit_created_desc ON public.audit_log USING btree (created_at DESC);

-- audit_log.idx_audit_not_login
CREATE INDEX idx_audit_not_login ON public.audit_log USING btree (created_at DESC) WHERE ((action)::text <> 'LOGIN'::text);

-- audit_log.idx_audit_action_date
CREATE INDEX idx_audit_action_date ON public.audit_log USING btree (action, created_at);

-- audit_log.ix_audit_log_created_at
CREATE INDEX ix_audit_log_created_at ON public.audit_log USING btree (created_at);

-- audit_log.idx_audit_resource
CREATE INDEX idx_audit_resource ON public.audit_log USING btree (resource_type, resource_id);

-- audit_log.ix_audit_log_resource_type
CREATE INDEX ix_audit_log_resource_type ON public.audit_log USING btree (resource_type);

-- audit_log.idx_audit_user_action
CREATE INDEX idx_audit_user_action ON public.audit_log USING btree (user_id, action);

-- audit_log.ix_audit_log_action
CREATE INDEX ix_audit_log_action ON public.audit_log USING btree (action);
