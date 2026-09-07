
output "network_id" {
  description = "ID of diploma VPC network"
  value       = yandex_vpc_network.diploma_network.id
}

output "public_subnet_d_id" {
  description = "ID of public subnet in ru-central1-d"
  value       = yandex_vpc_subnet.public_d.id
}

output "private_subnet_d_id" {
  description = "ID of private subnet in ru-central1-d"
  value       = yandex_vpc_subnet.private_d.id
}

output "private_subnet_a_id" {
  description = "ID of private subnet in ru-central1-a"
  value       = yandex_vpc_subnet.private_a.id
}
output "bastion_external_ip" {
  description = "External IPv4 address of bastion host"
  value       = yandex_compute_instance.bastion.network_interface[0].nat_ip_address
}

output "bastion_internal_ip" {
  description = "Internal IPv4 address of bastion host"
  value       = yandex_compute_instance.bastion.network_interface[0].ip_address
}

output "bastion_fqdn" {
  description = "Internal FQDN of bastion host"
  value       = yandex_compute_instance.bastion.fqdn
}

output "web_01_internal_ip" {
  description = "Internal IPv4 address of web-01"
  value       = yandex_compute_instance.web_01.network_interface[0].ip_address
}

output "web_01_fqdn" {
  description = "Internal FQDN of web-01"
  value       = yandex_compute_instance.web_01.fqdn
}

output "web_02_internal_ip" {
  description = "Internal IPv4 address of web-02"
  value       = yandex_compute_instance.web_02.network_interface[0].ip_address
}

output "web_02_fqdn" {
  description = "Internal FQDN of web-02"
  value       = yandex_compute_instance.web_02.fqdn
}
output "alb_external_ip" {
  description = "Public IPv4 address of Application Load Balancer"
  value       = yandex_alb_load_balancer.web_alb.listener[0].endpoint[0].address[0].external_ipv4_address[0].address
}

output "zabbix_external_ip" {
  description = "Public IPv4 address of Zabbix server"
  value       = yandex_compute_instance.zabbix.network_interface[0].nat_ip_address
}

output "zabbix_internal_ip" {
  description = "Internal IPv4 address of Zabbix server"
  value       = yandex_compute_instance.zabbix.network_interface[0].ip_address
}

output "zabbix_fqdn" {
  description = "Internal FQDN of Zabbix server"
  value       = yandex_compute_instance.zabbix.fqdn
}

output "elasticsearch_internal_ip" {
  description = "Internal IPv4 address of Elasticsearch server"
  value       = yandex_compute_instance.elasticsearch.network_interface[0].ip_address
}

output "elasticsearch_fqdn" {
  description = "Internal FQDN of Elasticsearch server"
  value       = yandex_compute_instance.elasticsearch.fqdn
}
output "kibana_internal_ip" {
  description = "Internal IPv4 address of Kibana server"
  value       = yandex_compute_instance.kibana.network_interface[0].ip_address
}

output "kibana_external_ip" {
  description = "External IPv4 address of Kibana server"
  value       = yandex_compute_instance.kibana.network_interface[0].nat_ip_address
}

output "kibana_fqdn" {
  description = "Internal FQDN of Kibana server"
  value       = yandex_compute_instance.kibana.fqdn
}
