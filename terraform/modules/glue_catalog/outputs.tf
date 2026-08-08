output "database_name" {
  description = "Glue database name."
  value       = aws_glue_catalog_database.this.name
}

output "table_names" {
  description = "Map of logical name -> Glue table name."
  value = {
    payments_events  = aws_glue_catalog_table.payments_events.name
    payments_current = aws_glue_catalog_table.payments_current.name
  }
}
