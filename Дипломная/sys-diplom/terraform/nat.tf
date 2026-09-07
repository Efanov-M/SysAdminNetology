resource "yandex_vpc_gateway" "nat_gateway" {
  name        = "diploma-nat-gateway"
  description = "NAT gateway for private diploma subnets"

  shared_egress_gateway {}
}

resource "yandex_vpc_route_table" "private_route_table" {
  name        = "private-route-table"
  description = "Default internet route for private subnets"
  network_id  = yandex_vpc_network.diploma_network.id

  static_route {
    destination_prefix = "0.0.0.0/0"
    gateway_id         = yandex_vpc_gateway.nat_gateway.id
  }
}
