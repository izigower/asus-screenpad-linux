# Banc d'essai de ./setup : Arch vierge, matériel et session simulés.
FROM archlinux:latest
RUN pacman -Sy --noconfirm --needed python sudo procps-ng which lua >/dev/null \
 && useradd -m test \
 && echo 'test ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/00-test && chmod 440 /etc/sudoers.d/00-test
COPY stubs/ /usr/local/sbin/
COPY omarchy/ /usr/share/omarchy/
RUN chmod +x /usr/local/sbin/* && mkdir -m 777 /fake
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/bin
