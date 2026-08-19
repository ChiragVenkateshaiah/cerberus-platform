output "state_machine_arn" {
  description = "The orchestration state machine's ARN."
  value       = aws_sfn_state_machine.orchestration.arn
}

output "state_machine_name" {
  description = "The orchestration state machine's name."
  value       = aws_sfn_state_machine.orchestration.name
}
