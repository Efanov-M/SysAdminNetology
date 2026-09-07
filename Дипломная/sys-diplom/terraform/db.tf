resource "yandex_compute_instance" "db_01" {
  name        = "db-01"
  hostname    = "db-01"
  description = "PostgreSQL primary database server"
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
    security_group_ids = [yandex_vpc_security_group.db_sg.id]
  }

  metadata = {
    enable-oslogin = "false"
    ssh-keys       = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
  }
}

resource "yandex_compute_instance" "db_02" {
  name        = "db-02"
  hostname    = "db-02"
  description = "PostgreSQL standby database server"
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
    security_group_ids = [yandex_vpc_security_group.db_sg.id]
  }

  metadata = {
    enable-oslogin = "false"
    ssh-keys       = "ubuntu:${trimspace(file(pathexpand(var.ssh_public_key_path)))}"
  }
}
