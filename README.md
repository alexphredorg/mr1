# Langmuir MR-1 configuration for LinuxCNC

My LinuxCNC configuration for the Langmuir MR-1 gantry mill.

Notes on the configuration:
* This uses the stock MR1 stepper drivers, spindle (servo) drive, and tool probes.
* They are connected to the PC running LinuxCNC using a MESA 7i96S.
* Tool changes use probing to set the tool height.  This uses the Langmuir probe and tool setter.

Notes on my conversion can be found at: https://1drv.ms/u/s!AqokoOqNPTKZkpR0nkyh90eFzuL-rw

Setup steps:
* Use this install guide for Debian 12 and LinuxCNC: https://github.com/Lcvette/qtpyvcp-bookworm-installer
* This guide is helpful for specific tips and tricks: https://docs.google.com/document/d/1jeV_4VKzVmOIzbB-ytcgsW2I_PhCm1x7oiw8VcLFdiY/edit
* mkdir ~/linuxcnc/configs
* git clone https://github.com/alexphredorg/mr1.git
* Check mr1.ini 
* source ~/dev/env/bin/activate
* linuxcnc, select mr1/mr1

Consider latest LinuxCNC drops from http://buildbot2.highlab.com/debian/dists/bookworm/2.9-uspace/
