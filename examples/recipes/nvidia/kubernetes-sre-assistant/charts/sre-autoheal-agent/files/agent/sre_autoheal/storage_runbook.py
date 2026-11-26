# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, human-only guest follow-up; this module executes nothing."""
import re
import shlex


def guest_steps(record):
    """Conditional simple-partition guidance, never guess an OS or LVM layout."""
    steps = [
        'Admin: review this incident, confirm the exact VM/PVC attachment and a usable backup or snapshot, then share an admin-approved procedure with the VM owner.',
        'VM owner: use your approved console/access method. The SRE agent does not log in, execute guest commands, stop or reboot the VM.',
        'Inside the guest, inspect the OS and storage layout: cat /etc/os-release; lsblk -b -o NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS; findmnt -o SOURCE,FSTYPE,TARGET.',
    ]
    if record.get('outcome') not in ('guest_growth_needed', 'guest_verification_needed', 'healed'):
        steps.append('Do not grow the guest partition or filesystem until the admin verifies PVC expansion completed, resize conditions cleared, and the guest sees the larger disk. The PVC expansion in this incident is not verified; investigate the PVC status/events first and do not repeat an outstanding resize.')
        return steps
    steps.append('Confirm the guest sees the larger disk. If it does not, stop and contact the virtualization/storage admin; do not repeat PVC expansion.')
    device = record.get('guest_device') or ''
    mount = record.get('guest_mount') or ''
    filesystem = record.get('guest_filesystem') or ''
    partition = re.fullmatch(r'((?:vd|sd|xvd)[a-z]+)([1-9][0-9]*)', device)
    mount_valid = (isinstance(mount, str) and mount.startswith('/')
                   and len(mount) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in mount))
    if (record.get('guest_mapping_current') and partition and mount_valid
            and filesystem in ('ext4', 'xfs')):
        disk, number = partition.groups()
        quoted_mount = shlex.quote(mount)
        steps.append(f'Only after the admin confirms /dev/{device} is the simple, growable partition for {quoted_mount} on /dev/{disk}, with no LVM, encryption, RAID or intervening partition: check tool availability with command -v growpart and command -v {"resize2fs" if filesystem == "ext4" else "xfs_growfs"}. Tool packages depend on the guest OS; do not select a procedure from the distro name alone.')
        steps.append(f'Preview the partition change first: sudo growpart --dry-run /dev/{disk} {number}. Stop on errors or an unexpected partition layout.')
        steps.append(f'After approval, if the partition is smaller than the enlarged disk: sudo growpart /dev/{disk} {number}. Confirm the kernel reports the larger partition before the filesystem step; NOCHANGE can mean it is already grown, but must be verified.')
        command = f'sudo resize2fs /dev/{device}' if filesystem == 'ext4' else f'sudo xfs_growfs {quoted_mount}'
        steps.append(f'For the verified {filesystem} filesystem only, grow it to its available underlying size: {command}. Stop on errors; do not substitute tools for another filesystem.')
        steps.append(f'Verify the affected mount: df -h -- {quoted_mount}; findmnt --target {quoted_mount}; lsblk -b. Send the timestamped results to the admin.')
    else:
        steps.append('Current simple-partition/filesystem mapping is unavailable or unsupported. Admin must obtain current lsblk/findmnt output and supply an admin-approved procedure; do not apply generic growpart/resize2fs commands to LVM, encrypted, RAID, Windows or unknown layouts.')
    steps.append('Agent: continue PVC size and guest-usage observation. Guest-agent responses without source timestamps are not proof of recovery. Keep the operation locked until the admin verifies recovery and reconciles the recorded incident; never shrink the PVC or clear a lock during an outstanding resize.')
    return steps
