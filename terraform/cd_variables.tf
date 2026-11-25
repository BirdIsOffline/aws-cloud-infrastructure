variable "github_deployment_identity" {
  description = "Externally supplied immutable GitHub identifiers; never place real values in public source."
  type = object({
    owner_id      = string
    repository_id = string
    actor_ids     = set(string)
  })
  sensitive = true

  validation {
    condition = (
      can(regex("^[1-9][0-9]{0,19}$", var.github_deployment_identity.owner_id)) &&
      can(regex("^[1-9][0-9]{0,19}$", var.github_deployment_identity.repository_id)) &&
      length(var.github_deployment_identity.actor_ids) > 0 &&
      length(var.github_deployment_identity.actor_ids) <= 5 &&
      alltrue([for id in var.github_deployment_identity.actor_ids : can(regex("^[1-9][0-9]{0,19}$", id))])
    )
    error_message = "Supply nonempty immutable numeric owner, repository, and approved actor IDs externally."
  }
}
