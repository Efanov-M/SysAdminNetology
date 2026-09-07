resource "yandex_compute_instance" "web_01" {
  name        = "web-01"
  hostname    = "web-01"
  description = "Private web server 01"
  zone        = "ru-central1-d"

  platform_id = "standard-v3"

  resources {
    cores         = 2
    memory        = 2
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
    subnet_id          = yandex_vpc_subnet.private_d.id
    nat                = false
    security_group_ids = [yandex_vpc_security_group.web_sg.id]
  }

  metadata = {
    enable-oslogin = "false"
    ssh-keys       = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
  }
}

resource "yandex_compute_instance" "web_02" {
  name        = "web-02"
  hostname    = "web-02"
  description = "Private web server 02"
  zone        = "ru-central1-a"

  platform_id = "standard-v3"

  resources {
    cores         = 2
    memory        = 2
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
    subnet_id          = yandex_vpc_subnet.private_a.id
    nat                = false
    security_group_ids = [yandex_vpc_security_group.web_sg.id]
  }

  metadata = {
    enable-oslogin = "false"
    ssh-keys       = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
  }
}
