DEFINE_DEVICE_TYPE(SAA1099, saa1099_device, "saa1099", "Philips SAA1099")

void saa1099_device::data_w(u8 data)
{
	int reg = m_selected_reg;
	int ch;

	/* first update the stream to this point in time */
	m_stream->update();

	switch (reg)
	{
	/* channel i amplitude */
	case 0x00:  case 0x01:  case 0x02:  case 0x03:  case 0x04:  case 0x05:
		ch = reg & 7;
		m_channels[ch].amplitude[LEFT] = amplitude_lookup[data & 0x0f];
		m_channels[ch].amplitude[RIGHT] = amplitude_lookup[(data >> 4) & 0x0f];
		break;
	/* channel i frequency */
	case 0x08:  case 0x09:  case 0x0a:  case 0x0b:  case 0x0c:  case 0x0d:
		ch = reg & 7;
		m_channels[ch].frequency = data & 0xff;
		break;
	/* channel i octave */
	case 0x10:  case 0x11:  case 0x12:
		ch = (reg - 0x10) << 1;
		m_channels[ch + 0].octave = data & 0x07;
		m_channels[ch + 1].octave = (data >> 4) & 0x07;
		break;
	/* channel i frequency enable */
	case 0x14:
		for (ch = 0; ch < 6; ch++)
			m_channels[ch].freq_enable = BIT(data, ch);
		break;
	/* channel i noise enable */
	case 0x15:
		for (ch = 0; ch < 6; ch++)
			m_channels[ch].noise_enable = BIT(data, ch);
		break;
	/* noise generators parameters */
	case 0x16:
		m_noise_params[0] = data & 0x03;
		m_noise_params[1] = (data >> 4) & 0x03;
		break;
	/* envelope generators parameters */
	case 0x18:  case 0x19:
		ch = reg - 0x18;
		m_env_reverse_right[ch] = BIT(data, 0);
		m_env_mode[ch] = (data >> 1) & 0x07;
		m_env_bits[ch] = BIT(data, 4);
		m_env_clock[ch] = BIT(data, 5);
		m_env_enable[ch] = BIT(data, 7);
		/* reset the envelope */
		m_env_step[ch] = 0;
		break;
	/* channels enable & reset generators */
	case 0x1c:
		m_all_ch_enable = BIT(data, 0);
		m_sync_state = BIT(data, 1);
		if (BIT(data, 1))
		{
			/* Synch & Reset generators */
			logerror("%s: -reg 0x1c- Chip reset\n", machine().describe_context());
			for (int i = 0; i < 6; i++)
			{
				m_channels[i].level = 0;
				m_channels[i].counter = m_channels[i].freq();
			}
		}
		break;
	default:    /* Error! */
		if (data != 0)
			logerror("%s: Unknown operation (reg:%02x, data:%02x)\n", machine().describe_context(), reg, data);
	}
}
