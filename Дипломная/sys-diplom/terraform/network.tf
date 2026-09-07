resource "yandex_vpc_network" "diploma_network" {
  name        = "diploma-network"
  description = "VPC network for diploma infrastructure"
}

resource "yandex_vpc_subnet" "public_d" {
  name           = "public-subnet-d"
  description    = "Public subnet in ru-central1-d"
  zone           = "ru-central1-d"
  network_id     = yandex_vpc_network.diploma_network.id
  v4_cidr_blocks = ["10.10.10.0/24"]
}

resource "yandex_vpc_subnet" "private_d" {
  name           = "private-subnet-d"
  description    = "Private subnet in ru-central1-d"
  zone           = "ru-central1-d"
  network_id     = yandex_vpc_network.diploma_network.id
  v4_cidr_blocks = ["10.10.20.0/24"]
  route_table_id = yandex_vpc_route_table.private_route_table.id
}

resource "yandex_vpc_subnet" "private_a" {
  name           = "private-subnet-a"
  description    = "Private subnet in ru-central1-a"
  zone           = "ru-central1-a"
  network_id     = yandex_vpc_network.diploma_network.id
  v4_cidr_blocks = ["10.10.30.0/24"]
  route_table_id = yandex_vpc_route_table.private_route_table.id
}
