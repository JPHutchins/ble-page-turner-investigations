import pytest

from page_turner.guard import Access, Allowed, Denied, judge
from page_turner.kindle import md5_command, pull_command, push_command

READS = (
	"cat /proc/bus/input/devices",
	"uname -a; cat /etc/prettyversion.txt",
	"ls -la /mnt/us/kindle-button-mapper 2>/dev/null",
	"grep -B1 -A9 'Name=\"F3' /proc/bus/input/devices",
	"tail -n 50 /var/log/kindle-button-mapper.log | grep -E 'Reading events|starting'",
	"df -h /mnt/us /var/local /tmp && cat /proc/mounts",
	"initctl status kindle-button-mapper",
	"/mnt/us/kindle-button-mapper/kindle-button-mapper --version",
	"timeout 5 hexdump -C /dev/input/event2",
	"wget -qO- 'http://127.0.0.1:8322/resolve?name=F3%20Touchscreen&uniq=EB:80:03:88:70:8B'",
	"md5sum /mnt/us/kindle-button-mapper/kindle-button-mapper 2>&1",
)

WRITES = (
	"mkdir -p /mnt/us/kbm-hil/backup",
	"cp -p /mnt/us/kindle-button-mapper/config.ini /mnt/us/kbm-hil/backup/",
	"cp /var/log/kindle-button-mapper.log /mnt/us/kbm-hil/",
	"mv -f /mnt/us/kindle-button-mapper/x.new /mnt/us/kindle-button-mapper/x",
	"chmod +x /mnt/us/kindle-button-mapper/kindle-button-mapper",
	"initctl stop kindle-button-mapper && initctl start kindle-button-mapper",
	"kill -TERM 1234",
	"rm -rf /var/local/mesquite/com.lzampier.mappermanager",
	"rm -r /mnt/us/kbm-hil/staging",
	"echo 0 > /mnt/us/kbm-hil/marker",
	push_command("/mnt/us/kbm-hil/kindle-button-mapper.new"),
)

REFUSED = (
	("/usr/sbin/mntroot rw", "mntroot"),
	("mount -o remount,rw /", "mount"),
	("reboot", "reboot"),
	("dd if=/dev/zero of=/dev/mmcblk0", "dd"),
	("sqlite3 /var/local/appreg.db 'select 1'", "sqlite3"),
	("sh -c 'rm -rf /'", "sh"),
	("cat $(echo /etc/shadow)", "substitution"),
	("cat `echo x`", "substitution"),
	("lipc-set-prop com.lab126.powerd preventScreenSaver 1", "lipc-set-prop"),
	("killall kindle-button-mapper", "killall"),
	("echo x > /etc/upstart/kindle-button-mapper.conf", "redirects outside"),
	("cp /mnt/us/kbm-hil/x /etc/udev/rules.d/", "only into"),
	("rm -rf /mnt/us/kindle-button-mapper", "whole install"),
	("rm -r /mnt/us/kindle-button-mapper/scripts", "rm -r"),
	("rm /mnt/us/kbm-hil/../documents/book.azw3", "only under"),
	("rm x.new", "absolute"),
	("initctl stop lab126_gui", "initctl"),
	("wget -qO- http://127.0.0.1:8322/capture?device=/dev/input/event2", "wget"),
	("wget -O /tmp/x http://example.com/", "wget"),
	("find /mnt/us -name '*.new' -delete", "find"),
	("sleep 100 &", "background"),
	("(cd /etc && ls)", "subshells"),
	("tee /mnt/us/kbm-hil/x", "tee"),
	("sed -i s/a/b/ /mnt/us/kindle-button-mapper/config.ini", "sed"),
	("nc -l 9999", "not on the guard's list"),
	(push_command("/etc/passwd"), "redirects outside"),
)


@pytest.mark.parametrize("command", READS)
def test_reads_run_without_the_write_flag(command: str) -> None:
	assert judge(command, write=False) == Allowed(Access.READ)


@pytest.mark.parametrize("command", WRITES)
def test_writes_need_the_flag_and_stay_in_our_paths(command: str) -> None:
	assert isinstance(judge(command, write=False), Denied)
	assert judge(command, write=True) == Allowed(Access.WRITE)


@pytest.mark.parametrize(("command", "because"), REFUSED)
def test_some_commands_are_refused_even_with_the_flag(command: str, because: str) -> None:
	match judge(command, write=True):
		case Denied(reason):
			assert because in reason
		case allowed:
			pytest.fail(f"{command!r} was {allowed}")


def test_transfers_are_judged_like_any_command() -> None:
	assert judge(pull_command("/var/log/kindle-button-mapper.log"), write=False) == Allowed(
		Access.READ
	)
	assert judge(md5_command("/mnt/us/kbm-hil/a b.new"), write=False) == Allowed(Access.READ)
