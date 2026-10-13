variable "image" {
  type = string
}

variable "revision" {
  type = string
}

variable "namespace" {
  type = string
}

variable "hostname" {
  type = string
}

variable "runtime_variable" {
  type = string
}

# "production" keeps the original names, so release.yml needs no change.
# Any other value (e.g. "staging") gets its own job, service and Traefik
# router, so both copies can run in one cluster without colliding.
variable "env" {
  type    = string
  default = "production"
}

locals {
  name = var.env == "production" ? "access" : "access-${var.env}"
}

job "access" {
  id          = local.name
  name        = local.name
  datacenters = ["cs403bkk"]
  namespace   = var.namespace
  type        = "service"

  meta {
    revision = var.revision
  }

  group "web" {
    count = 1

    constraint {
      attribute = "${node.unique.name}"
      value     = "cs403bkk-nomad-1"
    }

    update {
      max_parallel      = 1
      health_check      = "checks"
      min_healthy_time  = "10s"
      healthy_deadline  = "3m"
      progress_deadline = "5m"
      auto_revert       = true
    }

    network {
      port "http" {
        to = 8000
      }
    }

    task "app" {
      driver = "docker"

      config {
        image = var.image
        ports = ["http"]
      }

      env {
        APP_REVISION = var.revision
      }

      template {
        data                 = <<EOH
DATABASE_URL={{ with nomadVar "${var.runtime_variable}" }}{{ .database_url | toJSON }}{{ end }}
SERVICE_TOKEN={{ with nomadVar "${var.runtime_variable}" }}{{ .service_token | toJSON }}{{ end }}
EOH
        destination          = "secrets/runtime.env"
        env                  = true
        perms                = "0600"
        change_mode          = "restart"
        error_on_missing_key = true
      }

      resources {
        cpu    = 300
        memory = 256
      }

      service {
        name     = local.name
        port     = "http"
        provider = "nomad"

        tags = [
          "traefik.enable=true",
          format("traefik.http.routers.%s.rule=Host(`%s`)", local.name, var.hostname),
          "traefik.http.routers.${local.name}.entrypoints=websecure",
          "traefik.http.routers.${local.name}.tls=true",
          "traefik.http.routers.${local.name}.tls.certresolver=letsencrypt",
        ]

        check {
          type     = "http"
          path     = "/health"
          interval = "10s"
          timeout  = "2s"
        }
      }
    }
  }
}
