# Langmuir MR-1 configuration for LinuxCNC

My LinuxCNC configuration for the Langmuir MR-1 gantry mill.

Notes on the configuration:
* I'm using the stock spindle (servo) drive, stepper motors and tool probes.  I've upgraded my stepper drives to Leadshine 
EM542S, but the configuration here is compatible with the stock steppers as long as you slow down the max velocities.
* My machine is connected to the PC running LinuxCNC using a MESA 7i96S and ethernet on a private network.
* Tool changes use probing to set the tool height.  This uses the Langmuir probe and tool setter.  The probe is tool 99 and
tool length probing is automatic for all tools other than 0 and 99.  When the probe is unloaded it is always measured.

Notes on my conversion can be found at: https://1drv.ms/u/s!AqokoOqNPTKZkpR0nkyh90eFzuL-rw

LinuxCNC on Debian 12 installation steps:
* This install guide will get Debian 12 + LinuxCNC together and includes useful tips and tricks: https://docs.google.com/document/d/1jeV_4VKzVmOIzbB-ytcgsW2I_PhCm1x7oiw8VcLFdiY/edit
* mkdir ~/linuxcnc/configs
* git clone https://github.com/alexphredorg/mr1.git
* Check mr1.ini 
* Start LinuxCNC and select mr1/mr1

Consider pulling the latest LinuxCNC drops from http://buildbot2.highlab.com/debian/dists/bookworm/2.9-uspace/

Screenshots:
![Main View window with backplot](screenshots/mainview.png)
