// synthetic source for the tests of the row tools: it is not DOSBox-X code

static Bitu Handler(void) {
	if (reg_ah == 0x06 || reg_ah == 0x07) {
		return CBRET_NONE;
	}
	dos.breakcheck = false;
	switch (reg_ah) {
	case 0x5a:
#if !defined(NOFILES)
		MEM_StrCopy(SegPhys(ds) + reg_dx, name1, DOSNAMEBUF);
		if (make_temp(name1, &handle)) {
			reg_ax = handle;
			CALLBACK_SCF(false);
		} else {
			reg_ax = dos.errorcode;
			CALLBACK_SCF(true);
		}
#else
		reg_ax = 1;
#endif
		break;
	case 0x5b:
		reg_ax = 0;
		break;
	}
	return CBRET_NONE;
}

static bool make_temp(char * name, uint16_t * entry) {
	size_t len = strlen(name);
	if (len == 0) {
		name[0] = '\\';
	}
	dos.errorcode = 0;
	for (int i = 0; i < 8; i++) {
		name[len + i] = 'A' + rand() % 26;
	}
	return create_file(name, entry);
}

static void Video(void) {
	if (!IS_VGA_ARCH) return;
	switch (reg_ah) {
	case 0x12:
		if (reg_bh == 0x55 && has_ati) {
			break;
		}
		switch (reg_bl) {
		case 0x31:
			if (reg_al > 1) {
				reg_al = 0;
				break;
			}
			reg_al = 0x12;
			break;
		}
		break;
	}
}
