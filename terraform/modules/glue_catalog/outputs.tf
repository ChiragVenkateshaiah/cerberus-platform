output "database_name" {
  description = "Glue database name."
  value       = aws_glue_catalog_database.this.name
}

output "table_names" {
  description = "Map of logical name -> Glue table name."
  value = {
    # A literal since 8.5: the Iceberg table is created by the silver job,
    # not this module, but its name is fixed and the IAM grants need it.
    payments_events  = "payments_events"
    payments_current = aws_glue_catalog_table.payments_current.name
  }
}

# Kept out of table_names on purpose: that map feeds cerberus-serving's
# catalog grant, and serving has no business with bronze (8.4).
output "bronze_table_names" {
  description = "Bronze tables for the data-quality suite (8.4); read by cerberus-transform only."
  value = {
    bronze_payments_raw  = aws_glue_catalog_table.bronze_payments_raw.name
    bronze_payments_bulk = aws_glue_catalog_table.bronze_payments_bulk.name
  }
}
