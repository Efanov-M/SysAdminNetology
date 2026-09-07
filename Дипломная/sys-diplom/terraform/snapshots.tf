resource "yandex_compute_snapshot_schedule" "daily" {
  name        = "diploma-daily-snapshots"
  description = "Daily snapshots of diploma infrastructure VM boot disks"

  schedule_policy {
    expression = "0 1 ? * *"
  }

  retention_period = "168h0m0s"

  snapshot_spec {
    description = "Automatic daily snapshot for diploma infrastructure"

    labels = {
      project = "diploma"
      type    = "daily"
    }
  }

  disk_ids = [
    yandex_compute_instance.bastion.boot_disk[0].disk_id,
    yandex_compute_instance.web_01.boot_disk[0].disk_id,
    yandex_compute_instance.web_02.boot_disk[0].disk_id,
    yandex_compute_instance.zabbix.boot_disk[0].disk_id,
    yandex_compute_instance.elasticsearch.boot_disk[0].disk_id,
    yandex_compute_instance.kibana.boot_disk[0].disk_id,
    yandex_compute_instance.db_01.boot_disk[0].disk_id,
    yandex_compute_instance.db_02.boot_disk[0].disk_id,
  ]
}
