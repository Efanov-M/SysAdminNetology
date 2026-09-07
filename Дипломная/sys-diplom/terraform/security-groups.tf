resource "yandex_vpc_security_group" "bastion_sg" {
  name        = "bastion-sg"
  description = "Security group for bastion host"
  network_id  = yandex_vpc_network.diploma_network.id

  ingress {
    protocol       = "TCP"
    description    = "SSH from administrator public IP"
    v4_cidr_blocks = [var.admin_cidr]
    #v4_cidr_blocks = ["0.0.0.0/0"]
    port = 22
  }

  egress {
    protocol       = "ANY"
    description    = "Allow outbound traffic"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "web_sg" {
  name        = "web-sg"
  description = "Security group for private web servers"
  network_id  = yandex_vpc_network.diploma_network.id

  ingress {
    protocol          = "TCP"
    description       = "SSH only from bastion"
    security_group_id = yandex_vpc_security_group.bastion_sg.id
    port              = 22
  }

  ingress {
    protocol    = "TCP"
    description = "HTTP from internal VPC"
    v4_cidr_blocks = [
      "10.10.10.0/24",
      "10.10.20.0/24",
      "10.10.30.0/24"
    ]
    port = 80
  }

  ingress {
    protocol          = "TCP"
    description       = "Application Load Balancer health checks"
    predefined_target = "loadbalancer_healthchecks"
    port              = 80
  }

  egress {
    protocol       = "ANY"
    description    = "Allow outbound traffic through NAT gateway"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "zabbix_sg" {
  name        = "zabbix-sg"
  description = "Security group for Zabbix server"
  network_id  = yandex_vpc_network.diploma_network.id

  ingress {
    protocol          = "TCP"
    description       = "SSH only from bastion"
    security_group_id = yandex_vpc_security_group.bastion_sg.id
    port              = 22
  }

  ingress {
    protocol       = "TCP"
    description    = "Zabbix web interface from administrator"
    v4_cidr_blocks = [var.admin_cidr]
    port           = 80
  }

  ingress {
    protocol    = "TCP"
    description = "Zabbix active agents from diploma VPC"
    v4_cidr_blocks = [
      "10.10.10.0/24",
      "10.10.20.0/24",
      "10.10.30.0/24"
    ]
    port = 10051
  }

  egress {
    protocol       = "ANY"
    description    = "Allow outbound traffic"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "elasticsearch_sg" {
  name        = "elasticsearch-sg"
  description = "Security group for Elasticsearch server"
  network_id  = yandex_vpc_network.diploma_network.id

  ingress {
    protocol          = "TCP"
    description       = "SSH only from bastion"
    security_group_id = yandex_vpc_security_group.bastion_sg.id
    port              = 22
  }

  ingress {
    protocol    = "TCP"
    description = "Elasticsearch API from diploma VPC"
    v4_cidr_blocks = [
      "10.10.10.0/24",
      "10.10.20.0/24",
      "10.10.30.0/24"
    ]
    port = 9200
  }

  egress {
    protocol       = "ANY"
    description    = "Allow outbound traffic through NAT gateway"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "kibana_sg" {
  name        = "kibana-sg"
  description = "Security group for Kibana server"
  network_id  = yandex_vpc_network.diploma_network.id

  ingress {
    protocol          = "TCP"
    description       = "SSH only from bastion"
    security_group_id = yandex_vpc_security_group.bastion_sg.id
    port              = 22
  }

  ingress {
    protocol       = "TCP"
    description    = "Kibana web interface from administrator IP"
    v4_cidr_blocks = [var.admin_cidr]
    port           = 5601
  }

  egress {
    protocol       = "ANY"
    description    = "Allow outbound traffic"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "db_sg" {
  name        = "db-sg"
  description = "Security group for PostgreSQL primary and standby servers"
  network_id  = yandex_vpc_network.diploma_network.id

  ingress {
    protocol          = "TCP"
    description       = "SSH only from bastion"
    security_group_id = yandex_vpc_security_group.bastion_sg.id
    port              = 22
  }

  ingress {
    protocol          = "TCP"
    description       = "PostgreSQL connections from web servers"
    security_group_id = yandex_vpc_security_group.web_sg.id
    port              = 5432
  }

  ingress {
    protocol    = "TCP"
    description = "PostgreSQL streaming replication between private database subnets"
    v4_cidr_blocks = [
      "10.10.20.0/24",
      "10.10.30.0/24"
    ]
    port = 5432
  }

  egress {
    protocol       = "ANY"
    description    = "Allow outbound traffic through NAT gateway"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}
