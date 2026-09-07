resource "yandex_compute_instance" "kibana" {
  name        = "kibana"
  hostname    = "kibana"
  description = "Kibana server for centralized log visualization"
  zone        = "ru-central1-d"

  platform_id = "standard-v3"

  resources {
    cores         = 2
    memory        = 4
    core_fraction = 20
  }

  scheduling_policy {
    preemptible = true
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      type     = "network-hdd"
      size     = 10
    }
  }

  network_interface {
    subnet_id          = yandex_vpc_subnet.public_d.id
    nat                = true
    security_group_ids = [yandex_vpc_security_group.kibana_sg.id]
  }

  metadata = {
    enable-oslogin = "false"
    ssh-keys       = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
  }
}
