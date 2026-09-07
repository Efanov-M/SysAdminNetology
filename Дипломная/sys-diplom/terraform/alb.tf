resource "yandex_alb_target_group" "web_target_group" {
  name        = "web-target-group"
  description = "Target group for diploma web servers"

  target {
    subnet_id  = yandex_vpc_subnet.private_d.id
    ip_address = yandex_compute_instance.web_01.network_interface[0].ip_address
  }

  target {
    subnet_id  = yandex_vpc_subnet.private_a.id
    ip_address = yandex_compute_instance.web_02.network_interface[0].ip_address
  }
}

resource "yandex_alb_backend_group" "web_backend_group" {
  name        = "web-backend-group"
  description = "Backend group for diploma web servers"

  http_backend {
    name             = "web-backend"
    port             = 80
    target_group_ids = [yandex_alb_target_group.web_target_group.id]

    healthcheck {
      timeout             = "5s"
      interval            = "5s"
      healthy_threshold   = 2
      unhealthy_threshold = 2

      http_healthcheck {
        path = "/health"
      }
    }
  }
}

resource "yandex_alb_http_router" "web_router" {
  name        = "web-router"
  description = "HTTP router for diploma website"
}

resource "yandex_alb_virtual_host" "web_virtual_host" {
  name           = "web-virtual-host"
  http_router_id = yandex_alb_http_router.web_router.id

  route {
    name = "web-route"

    http_route {
      http_match {
        path {
          prefix = "/"
        }
      }

      http_route_action {
        backend_group_id = yandex_alb_backend_group.web_backend_group.id
      }
    }
  }
}

resource "yandex_alb_load_balancer" "web_alb" {
  name        = "web-alb"
  description = "Public Application Load Balancer for diploma website"
  network_id  = yandex_vpc_network.diploma_network.id

  allocation_policy {
    location {
      zone_id   = "ru-central1-d"
      subnet_id = yandex_vpc_subnet.public_d.id
    }
  }

  listener {
    name = "http-listener"

    endpoint {
      address {
        external_ipv4_address {}
      }

      ports = [80]
    }

    http {
      handler {
        http_router_id = yandex_alb_http_router.web_router.id
      }
    }
  }
}
