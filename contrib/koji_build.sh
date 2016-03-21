echo 'Please run this script from vdsm main folder'
echo '============================================'

make distclean
./autogen.sh \
    --system \
    --disable-ovirt-vmconsole \
    --enable-vhostmd-hook \
    --enable-hooks
make srpm

echo
echo 'Finish to compile VDSM for koji Fedora build'
echo 'Use output srp.rpm to import fedpkg'
