/* 재생 중인 곡의 디코더는 소리 해제 후 닫는다. */
typedef struct {
    ma_sound sound;
    ma_decoder decoder;
} fd_music;

void fd_music_close(fd_music* music) {
    ma_sound_uninit(&music->sound);
    ma_decoder_uninit(&music->decoder);
    free(music);
}

fd_music* fd_music_open(ma_engine* engine, const wchar_t* path, float gain) {
    fd_music* music = calloc(1, sizeof(*music));
    if (!music) return NULL;
    if (ma_decoder_init_file_w(path, NULL, &music->decoder) != MA_SUCCESS) {
        free(music);
        return NULL;
    }
    if (ma_sound_init_from_data_source(engine, &music->decoder, MA_SOUND_FLAG_NO_SPATIALIZATION,
                                       NULL, &music->sound) != MA_SUCCESS) {
        ma_decoder_uninit(&music->decoder);
        free(music);
        return NULL;
    }
    ma_sound_set_looping(&music->sound, MA_TRUE);
    ma_sound_set_volume(&music->sound, gain);
    if (ma_sound_start(&music->sound) != MA_SUCCESS) {
        fd_music_close(music);
        return NULL;
    }
    return music;
}
