#!/bin/bash
# Copy the running Armbian system from the SD card to the built-in eMMC, then make the eMMC bootable
set -e
emmc=/dev/mmcblk2

# Never touch the disk the system is running from
if findmnt -n -o SOURCE / | grep -q mmcblk2; then
    echo "STOP: the system is running from the eMMC"
    exit 1
fi
echo "== partition"
umount ${emmc}p* 2>/dev/null || true
wipefs -a -q ${emmc}
echo "8192,,83" | sfdisk -q ${emmc}
sleep 2
mkfs.ext4 -q -F -L armbi_emmc ${emmc}p1
new_uuid=$(blkid -s UUID -o value ${emmc}p1)
echo "new UUID: $new_uuid"
echo "== copy"
mkdir -p /mnt/emmc
mount ${emmc}p1 /mnt/emmc
rsync -aAXHx --info=stats1 --exclude=/mnt/emmc / /mnt/emmc/
mkdir -p /mnt/emmc/dev /mnt/emmc/proc /mnt/emmc/sys /mnt/emmc/run /mnt/emmc/tmp /mnt/emmc/var/log
echo "== settings"
old_uuid=$(findmnt -n -o UUID /)
sed -i "s/$old_uuid/$new_uuid/" /mnt/emmc/etc/fstab /mnt/emmc/boot/armbianEnv.txt
grep -H "$new_uuid" /mnt/emmc/etc/fstab /mnt/emmc/boot/armbianEnv.txt
echo "== bootloader"
dd if=/dev/zero of=${emmc} bs=32k count=63 seek=1 status=none
dd if=$(ls /usr/lib/linux-u-boot-*/u-boot-rockchip-with-spl.bin | head -1) of=${emmc} bs=32k seek=1 conv=notrunc status=none
sync
ls /mnt/emmc/boot/overlay-user/
df -h /mnt/emmc
umount /mnt/emmc
echo "EMMC-COPY-OK"
